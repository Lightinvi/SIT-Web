from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from app import create_app
from app.api.auth import digest
from app.services.oauth import OAuthError, authenticate


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-secret',
            'SQL_DATABASE_PATH': str(Path(self.temp.name) / 'auth.sqlite3'),
            'DISCORD_CLIENT_ID': 'client', 'DISCORD_CLIENT_SECRET': 'secret',
            'DISCORD_REDIRECT_URI': 'http://localhost:5173/api/auth/discord/callback'})
        self.client = self.app.test_client()

    def start(self):
        response = self.client.get('/api/auth/discord/login')
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response.location).query)
        self.assertEqual(query['scope'], ['identify guilds.members.read'])
        return query['state'][0]

    def callback(self, state):
        return self.client.get('/api/auth/discord/callback', query_string={'state': state, 'code': 'test-code'})

    def test_success_session_logout_and_replay(self):
        state = self.start()
        with patch('app.api.auth.authenticate', return_value={'id': '123', 'name': '隊員'}) as auth:
            self.assertEqual(self.callback(state).location, '/')
            auth.assert_called_once()
            status = self.client.get('/api/auth/session')
            self.assertTrue(status.json['authenticated'])
            self.assertEqual(status.json['user']['name'], '隊員')
            self.assertEqual(status.headers['Cache-Control'], 'no-store')
            self.assertEqual(self.client.post('/api/auth/logout').status_code, 403)
            self.assertEqual(self.client.post('/api/auth/logout', headers={'X-CSRF-Token': status.json['csrf_token']}).status_code, 200)
            self.assertFalse(self.client.get('/api/auth/session').json['authenticated'])
            # Even restoring the original signed-session state cannot reuse it.
            with self.client.session_transaction() as session:
                session['oauth_state'] = state
            self.assertIn('invalid_state', self.callback(state).location)
            auth.assert_called_once()

    def test_nonmember_and_upstream_failure_never_login(self):
        for reason in ('not_member', 'pending_member', 'discord_unavailable'):
            with self.subTest(reason=reason):
                state = self.start()
                with patch('app.api.auth.authenticate', side_effect=OAuthError(reason)):
                    self.assertIn(reason, self.callback(state).location)
                self.assertFalse(self.client.get('/api/auth/session').json['authenticated'])

    def test_state_mismatch_expiration_and_cancellation(self):
        state = self.start()
        with patch('app.api.auth.authenticate') as auth:
            self.assertIn('invalid_state', self.callback('wrong').location)
            state = self.start()
            self.app.extensions['sql'].update('oauth_states', {'expires': 0}, {'id': digest(state)})
            self.assertIn('invalid_state', self.callback(state).location)
            state = self.start()
            response = self.client.get('/api/auth/discord/callback', query_string={'state': state, 'error': 'access_denied'})
            self.assertIn('cancelled', response.location)
            auth.assert_not_called()

    def test_session_expiration(self):
        state = self.start()
        with patch('app.api.auth.authenticate', return_value={'id': '123'}):
            self.callback(state)
        self.app.extensions['sql'].execute('UPDATE login_sessions SET expires=?', (time.time() - 1,))
        self.assertFalse(self.client.get('/api/auth/session').json['authenticated'])

    def test_missing_configuration(self):
        self.app.config['DISCORD_CLIENT_SECRET'] = ''
        self.assertIn('not_configured', self.client.get('/api/auth/discord/login').location)

    def test_membership_checked_live_with_oauth_token(self):
        with patch('app.services.oauth.discord_request', side_effect=[
            {'access_token': 'private-token'}, {'id': '123', 'username': 'name'},
            {'user': {'id': '123'}, 'nick': '群組暱稱'},
        ]) as request:
            result = authenticate('code', self.app.config)
            self.assertEqual(result['name'], '群組暱稱')
            self.assertEqual(request.call_args.args[0], 'users/@me/guilds/510386488639488001/member')
            self.assertEqual(request.call_args.kwargs, {'token': 'private-token'})
            self.assertNotIn('private-token', str(result))

    def test_pending_or_mismatched_member_rejected(self):
        for member in ({'user': {'id': '456'}}, {'user': {'id': '123'}, 'pending': True}):
            with patch('app.services.oauth.discord_request', side_effect=[
                {'access_token': 'token'}, {'id': '123'}, member,
            ]):
                with self.assertRaises(OAuthError):
                    authenticate('code', self.app.config)

    def test_bot_client_id_fallback_without_token_as_secret(self):
        with patch.dict('os.environ', {'DISCORD_CLIENT_ID': '',
                'DISCORD_BOT_CLIENT_ID': 'bot-application',
                'DISCORD_CLIENT_SECRET': '', 'DISCORD_BOT_TOKEN': 'bot-only'}):
            app = create_app({'TESTING': True, 'SECRET_KEY': 'test'})
            self.assertEqual(app.config['DISCORD_CLIENT_ID'], 'bot-application')
            self.assertEqual(app.config['DISCORD_CLIENT_SECRET'], '')
            self.assertIn('not_configured', app.test_client().get('/api/auth/discord/login').location)
        with patch.dict('os.environ', {'DISCORD_CLIENT_ID': 'explicit',
                'DISCORD_BOT_CLIENT_ID': 'fallback'}):
            self.assertEqual(create_app().config['DISCORD_CLIENT_ID'], 'explicit')

    def test_member_created_and_updated_on_successful_login(self):
        db = self.app.extensions['sql']
        user = {'id': '123456789012345678', 'username': 'original', 'name': '原名稱'}
        with patch('app.api.auth.authenticate', return_value=user):
            self.callback(self.start())
        first = db.select('member')[0]
        self.assertEqual(first['user_id'], user['id'])
        self.assertEqual(first['username'], 'original')
        self.assertEqual(first['display_name'], '原名稱')
        self.assertEqual(first['created_at'], first['last_login_at'])
        later = first['created_at'] + 60
        with patch('app.api.auth.authenticate', return_value={**user, 'username': 'updated', 'name': '新名稱'}):
            with patch('app.api.auth.time.time', return_value=later):
                self.callback(self.start())
        rows = db.select('member')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['created_at'], first['created_at'])
        self.assertEqual(rows[0]['last_login_at'], later)
        self.assertEqual(rows[0]['username'], 'updated')
        self.assertEqual(rows[0]['display_name'], '新名稱')
        with patch('app.api.auth.time.time', return_value=later):
            csrf = self.client.get('/api/auth/session').json['csrf_token']
            self.client.post('/api/auth/logout', headers={'X-CSRF-Token': csrf})
        self.assertEqual(len(db.select('member')), 1)

    def test_rejected_login_does_not_create_member(self):
        with patch('app.api.auth.authenticate', side_effect=OAuthError('not_member')):
            self.callback(self.start())
        self.assertFalse(self.app.extensions['sql'].table_exists('member'))

    def test_member_and_session_creation_roll_back_together(self):
        from app.sql import SQLSession
        import sqlite3
        state = self.start()
        insert = SQLSession.insert
        def fail_session(tx, table, values):
            if table == 'login_sessions':
                raise sqlite3.OperationalError('simulated write failure')
            return insert(tx, table, values)
        with patch('app.api.auth.authenticate', return_value={'id': '123', 'name': 'test'}):
            with patch.object(SQLSession, 'insert', fail_session):
                with self.assertRaises(sqlite3.OperationalError):
                    self.callback(state)
        db = self.app.extensions['sql']
        self.assertFalse(db.table_exists('member'))
        self.assertEqual(db.select('login_sessions'), [])
        self.assertFalse(self.client.get('/api/auth/session').json['authenticated'])

    def test_profile_requires_session_and_only_returns_own_member(self):
        self.assertEqual(self.client.get('/api/auth/profile').status_code, 401)
        with patch('app.api.auth.authenticate', return_value={'id': '123', 'username': 'alice', 'name': 'Alice'}):
            self.callback(self.start())
        db = self.app.extensions['sql']
        db.insert('member', {'user_id': '456', 'username': 'bob', 'display_name': 'Bob',
                             'created_at': 1, 'last_login_at': 1})
        response = self.client.get('/api/auth/profile?user_id=456')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.json['member']['user_id'], '123')
        self.assertEqual(set(response.json['member']), {'user_id', 'username', 'display_name', 'created_at', 'last_login_at', 'global_name', 'nickname', 'avatar_url', 'guild_joined_at'})
        csrf = self.client.get('/api/auth/session').json['csrf_token']
        self.client.post('/api/auth/logout', headers={'X-CSRF-Token': csrf})
        self.assertEqual(self.client.get('/api/auth/profile').status_code, 401)

    def test_profile_rejects_expired_session_and_handles_missing_record(self):
        with patch('app.api.auth.authenticate', return_value={'id': '123', 'name': 'Alice'}):
            self.callback(self.start())
        db = self.app.extensions['sql']
        db.delete('member', {'user_id': '123'})
        self.assertEqual(self.client.get('/api/auth/profile').status_code, 404)
        db.execute('UPDATE login_sessions SET expires=0')
        self.assertEqual(self.client.get('/api/auth/profile').status_code, 401)

    def test_stored_avatar_used_by_header_and_profile(self):
        user = {'id': '123', 'name': 'Name', 'username': 'name',
                'avatar_url': 'https://cdn.discordapp.com/embed/avatars/0.png',
                'global_name': 'Global', 'nickname': 'Nick', 'guild_joined_at': '2020-01-01T00:00:00+00:00'}
        with patch('app.api.auth.authenticate', return_value=user):
            self.callback(self.start())
        db = self.app.extensions['sql']
        db.update('member', {'avatar_url': 'https://cdn.discordapp.com/embed/avatars/1.png'}, {'user_id': '123'})
        profile = self.client.get('/api/auth/profile').json['member']
        header = self.client.get('/api/auth/session').json['user']
        self.assertEqual(header['avatar_url'], profile['avatar_url'])
        self.assertTrue(header['avatar_url'].endswith('1.png'))
        self.assertEqual(profile['nickname'], 'Nick')

    def test_legacy_member_schema_upgraded_without_data_loss(self):
        db = self.app.extensions['sql']
        db.execute('CREATE TABLE member (user_id TEXT PRIMARY KEY, username TEXT, display_name TEXT, created_at REAL NOT NULL, last_login_at REAL NOT NULL)')
        db.insert('member', {'user_id': '123', 'username': 'old', 'created_at': 1, 'last_login_at': 1})
        with patch('app.api.auth.authenticate', return_value={'id': '123', 'name': 'Updated', 'avatar_url': 'avatar'}):
            self.callback(self.start())
        row = db.select('member')[0]
        self.assertEqual(row['created_at'], 1)
        self.assertEqual(row['avatar_url'], 'avatar')
        self.assertEqual(len(db.select('member')), 1)
