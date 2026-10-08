"""Exercise OAuth verification, profile persistence, and server-side session boundaries."""
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
    """Validate authentication flows using a temporary database and mocked Discord."""
    def setUp(self):
        """Create a temporary database and configured app without contacting Discord.
        建立此測試案例所需的獨立環境與測試資料。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests。
        """
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-secret',
            'SQL_DATABASE_PATH': str(Path(self.temp.name) / 'auth.sqlite3'),
            'DISCORD_CLIENT_ID': 'client', 'DISCORD_CLIENT_SECRET': 'secret',
            'DISCORD_REDIRECT_URI': 'http://localhost:5173/api/auth/discord/callback'})
        self.client = self.app.test_client()

    def start(self):
        """Begin login, assert the authorization scope, and return the generated state.
        透過測試 HTTP 用戶端啟動 OAuth 登入。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            str: OAuth 授權網址中的 state。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests。
        """
        response = self.client.get('/api/auth/discord/login')
        self.assertEqual(response.status_code, 302)
        query = parse_qs(urlparse(response.location).query)
        self.assertEqual(query['scope'], ['identify guilds.members.read'])
        return query['state'][0]

    def callback(self, state):
        """Submit a test authorization code with the supplied callback state.
        以測試授權碼與指定 OAuth state 呼叫登入回呼端點。

        Args:
            state: 登入初始化產生的 OAuth state 字串。

        Returns:
            TestResponse: OAuth 回呼的测试 HTTP 回應。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests。
        """
        return self.client.get('/api/auth/discord/callback', query_string={'state': state, 'code': 'test-code'})

    def test_success_session_logout_and_replay(self):
        """Verify login, CSRF-protected logout, and rejection of a consumed OAuth state.
        驗證成功登入、登出及重播防護。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_success_session_logout_and_replay。
        """
        state = self.start()
        with patch('app.services.oauth.OAuthService.authenticate', return_value={'id': '123', 'name': '隊員'}) as auth:
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
        """Ensure membership failures and Discord outages cannot establish a login.
        驗證非群組成員或上游失敗不能登入。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_nonmember_and_upstream_failure_never_login。
        """
        for reason in ('not_member', 'pending_member', 'insufficient_role', 'discord_unavailable'):
            with self.subTest(reason=reason):
                state = self.start()
                with patch('app.services.oauth.OAuthService.authenticate', side_effect=OAuthError(reason)):
                    self.assertIn(reason, self.callback(state).location)
                self.assertFalse(self.client.get('/api/auth/session').json['authenticated'])

    def test_state_mismatch_expiration_and_cancellation(self):
        """Reject invalid or expired states and handle consent cancellation before authentication.
        驗證OAuth state 不符、過期及授權取消。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_state_mismatch_expiration_and_cancellation。
        """
        state = self.start()
        with patch('app.services.oauth.OAuthService.authenticate') as auth:
            self.assertIn('invalid_state', self.callback('wrong').location)
            state = self.start()
            self.app.extensions['sql'].update('oauth_states', {'expires': 0}, {'id': digest(state)})
            self.assertIn('invalid_state', self.callback(state).location)
            state = self.start()
            response = self.client.get('/api/auth/discord/callback', query_string={'state': state, 'error': 'access_denied'})
            self.assertIn('cancelled', response.location)
            auth.assert_not_called()

    def test_session_expiration(self):
        """Reject an expired login and remove its authenticated browser state.
        驗證登入到期失效。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_session_expiration。
        """
        state = self.start()
        with patch('app.services.oauth.OAuthService.authenticate', return_value={'id': '123'}):
            self.callback(state)
        self.app.extensions['sql'].execute('UPDATE login_sessions SET expires=?', (time.time() - 1,))
        self.assertFalse(self.client.get('/api/auth/session').json['authenticated'])

    def test_session_lasts_seven_days_without_sliding_database_expiry(self):
        """Keep a login valid for seven days and reject it at the exact deadline.
        驗證登入有效七日且查詢不延長資料庫到期時間。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_session_lasts_seven_days_without_sliding_database_expiry。
        """
        logged_in_at = int(time.time())
        lifetime = 7 * 24 * 60 * 60
        with patch('app.api.auth.time.time', return_value=logged_in_at):
            with patch('app.services.oauth.OAuthService.authenticate', return_value={'id': '123'}):
                self.callback(self.start())
        db = self.app.extensions['sql']
        deadline = logged_in_at + lifetime
        self.assertEqual(db.select('login_sessions')[0]['expires'], deadline)
        self.assertEqual(self.app.permanent_session_lifetime.total_seconds(), lifetime)
        cookie = self.client.get_cookie(self.app.config['SESSION_COOKIE_NAME'])
        self.assertEqual(cookie.expires.timestamp(), deadline)
        for elapsed in (8 * 60 * 60 + 1, lifetime - 1):
            with self.subTest(elapsed=elapsed), patch('app.api.auth.time.time', return_value=logged_in_at + elapsed):
                self.assertTrue(self.client.get('/api/auth/session').json['authenticated'])
                self.assertEqual(db.select('login_sessions')[0]['expires'], deadline)
        with patch('app.api.auth.time.time', return_value=deadline):
            self.assertFalse(self.client.get('/api/auth/session').json['authenticated'])
        self.assertEqual(db.select('login_sessions'), [])

    def test_database_session_uses_cookie_lifetime_configuration(self):
        """Use Flask's configured lifetime for both cookie and database expiration.
        驗證資料庫登入期限使用 Cookie 生命週期設定。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_database_session_uses_cookie_lifetime_configuration。
        """
        self.app.config['PERMANENT_SESSION_LIFETIME'] = 3600
        logged_in_at = int(time.time())
        with patch('app.api.auth.time.time', return_value=logged_in_at):
            with patch('app.services.oauth.OAuthService.authenticate', return_value={'id': '123'}):
                self.callback(self.start())
        expected = logged_in_at + 3600
        self.assertEqual(self.app.extensions['sql'].select('login_sessions')[0]['expires'], expected)
        cookie = self.client.get_cookie(self.app.config['SESSION_COOKIE_NAME'])
        self.assertEqual(cookie.expires.timestamp(), expected)

    def test_missing_configuration(self):
        """Redirect to a configuration error when the OAuth secret is missing.
        驗證缺少登入設定時回報錯誤。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_missing_configuration。
        """
        self.app.config['DISCORD_CLIENT_SECRET'] = ''
        self.assertIn('not_configured', self.client.get('/api/auth/discord/login').location)

    def test_membership_checked_live_with_oauth_token(self):
        """Verify live guild membership uses the OAuth bearer token without returning it.
        驗證透過 OAuth 權杖即時驗證群組身份。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_membership_checked_live_with_oauth_token。
        """
        with patch('app.services.oauth.discord_request', side_effect=[
            {'access_token': 'private-token'}, {'id': '123', 'username': 'name'},
            {'user': {'id': '123'}, 'nick': '群組暱稱', 'roles': ['578156037589172244']},
        ]) as request:
            result = authenticate('code', self.app.config)
            self.assertEqual(result['name'], '群組暱稱')
            self.assertEqual(request.call_args.args[0], 'users/@me/guilds/510386488639488001/member')
            self.assertEqual(request.call_args.kwargs, {'token': 'private-token'})
            self.assertNotIn('private-token', str(result))

    def test_each_login_role_accepts_live_member(self):
        """Allow each specified role independently through OAuth and profile persistence.
        驗證所有允許登入的身份組皆可通過即時驗證。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_each_login_role_accepts_live_member。
        """
        for role in ('578156037589172244', '749803225275695156', '513295891482804250', '1555051124334137468'):
            with self.subTest(role=role), patch('app.services.oauth.discord_request', side_effect=[
                {'access_token': 'token'}, {'id': '123', 'username': 'qualified'},
                {'user': {'id': '123'}, 'roles': [role]},
            ]):
                self.assertEqual(self.callback(self.start()).location, '/')
                self.assertTrue(self.client.get('/api/auth/session').json['authenticated'])
                self.assertEqual(self.client.get('/api/auth/profile').json['member']['access_role']['id'], role)
                self.assertEqual(len(self.app.extensions['sql'].select('member')), 1)

    def test_missing_or_unrelated_roles_never_create_member(self):
        """Deny visitors and malformed membership roles before creating a member or session.
        驗證缺少或無關身份組不建立成員。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_missing_or_unrelated_roles_never_create_member。
        """
        for roles in (None, [], ['unrelated-role'], '578156037589172244', [None], [['578156037589172244']]):
            with self.subTest(roles=roles), patch('app.services.oauth.discord_request', side_effect=[
                {'access_token': 'token'}, {'id': '123', 'username': 'visitor'},
                {'user': {'id': '123'}, 'roles': roles},
            ]):
                self.assertIn('insufficient_role', self.callback(self.start()).location)
                self.assertFalse(self.client.get('/api/auth/session').json['authenticated'])
                self.assertEqual(self.app.extensions['sql'].select('member'), [])
                self.assertEqual(self.app.extensions['sql'].select('login_sessions'), [])

    def test_role_loss_or_departure_preserves_existing_profile(self):
        """Recheck returning members live, retaining their saved profile after denial.
        驗證失去身份或離開群組仍保留歷史資料。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_role_loss_or_departure_preserves_existing_profile。
        """
        with patch('app.services.oauth.discord_request', side_effect=[
            {'access_token': 'token'}, {'id': '123', 'username': 'original'},
            {'user': {'id': '123'}, 'roles': ['578156037589172244']},
        ]):
            self.callback(self.start())
        db = self.app.extensions['sql']
        original = db.select('member')
        for membership, reason in (({'user': {'id': '123'}, 'roles': []}, 'insufficient_role'),
                                   (OAuthError('not_member'), 'not_member')):
            with self.subTest(reason=reason), patch('app.services.oauth.discord_request', side_effect=[
                {'access_token': 'token'}, {'id': '123', 'username': 'changed'}, membership,
            ]):
                self.assertIn(reason, self.callback(self.start()).location)
                self.assertFalse(self.client.get('/api/auth/session').json['authenticated'])
                self.assertEqual(db.select('member'), original)
                self.assertEqual(db.select('login_sessions'), [])

    def test_pending_or_mismatched_member_rejected(self):
        """Reject pending guild screening and mismatched Discord user identities.
        驗證拒絕待審核及身份不符的群組成員。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_pending_or_mismatched_member_rejected。
        """
        for member in ({'user': {'id': '456'}}, {'user': {'id': '123'}, 'pending': True}):
            with patch('app.services.oauth.discord_request', side_effect=[
                {'access_token': 'token'}, {'id': '123'}, member,
            ]):
                with self.assertRaises(OAuthError):
                    authenticate('code', self.app.config)

    def test_bot_client_id_fallback_without_token_as_secret(self):
        """Verify the bot application ID fallback never substitutes the bot token for a secret.
        驗證client ID 備援設定且不使用 Bot 權杖作為密鑰。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_bot_client_id_fallback_without_token_as_secret。
        """
        with patch.dict('os.environ', {'DISCORD_CLIENT_ID': '',
                'DISCORD_BOT_CLIENT_ID': 'bot-application',
                'DISCORD_CLIENT_SECRET': '', 'DISCORD_BOT_TOKEN': 'bot-only'}):
            app = create_app({'TESTING': True, 'SECRET_KEY': 'test'})
            self.assertEqual(app.config['DISCORD_CLIENT_ID'], 'bot-application')
            self.assertEqual(app.config['DISCORD_CLIENT_SECRET'], '')
            self.assertIn('not_configured', app.test_client().get('/api/auth/discord/login').location)
        with patch.dict('os.environ', {'DISCORD_CLIENT_ID': 'explicit',
                'DISCORD_BOT_CLIENT_ID': 'fallback'}):
            self.assertEqual(create_app({'TESTING': True}).config['DISCORD_CLIENT_ID'], 'explicit')

    def test_member_created_and_updated_on_successful_login(self):
        """Refresh profiles on login while preserving first-login time and records after logout.
        驗證成功登入新增或更新成員。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_member_created_and_updated_on_successful_login。
        """
        db = self.app.extensions['sql']
        user = {'id': '123456789012345678', 'username': 'original', 'name': '原名稱'}
        with patch('app.services.oauth.OAuthService.authenticate', return_value=user):
            self.callback(self.start())
        first = db.select('member')[0]
        self.assertEqual(first['userId'], user['id'])
        self.assertEqual(first['username'], 'original')
        self.assertEqual(first['displayName'], '原名稱')
        self.assertEqual(first['createdAt'], first['lastLoginAt'])
        later = first['createdAt'] + 60
        with patch('app.services.oauth.OAuthService.authenticate', return_value={**user, 'username': 'updated', 'name': '新名稱'}):
            with patch('app.api.auth.time.time', return_value=later):
                self.callback(self.start())
        rows = db.select('member')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['createdAt'], first['createdAt'])
        self.assertEqual(rows[0]['lastLoginAt'], later)
        self.assertEqual(rows[0]['username'], 'updated')
        self.assertEqual(rows[0]['displayName'], '新名稱')
        with patch('app.api.auth.time.time', return_value=later):
            csrf = self.client.get('/api/auth/session').json['csrf_token']
            self.client.post('/api/auth/logout', headers={'X-CSRF-Token': csrf})
        self.assertEqual(len(db.select('member')), 1)

    def test_rejected_login_does_not_create_member(self):
        """Ensure failed membership verification does not create a member record.
        驗證拒絕登入不建立成員。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_rejected_login_does_not_create_member。
        """
        with patch('app.services.oauth.OAuthService.authenticate', side_effect=OAuthError('not_member')):
            self.callback(self.start())
        self.assertEqual(self.app.extensions['sql'].select('member'), [])

    def test_member_and_session_creation_roll_back_together(self):
        """Roll back the member schema and profile when session persistence fails.
        驗證成員與登入紀錄建立一併回滾。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_member_and_session_creation_roll_back_together。
        """
        from app.sql import SQLSession
        import sqlite3
        state = self.start()
        insert = SQLSession.insert
        def fail_session(tx, table, values):
            """Simulate a database failure only when inserting the login session.
            在登入紀錄新增時注入失敗，其餘新增沿用原方法。

            Args:
                tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。
                table: 資料表名稱。
                values: 欄位名稱與資料值的對照表。

            Returns:
                object: 被包裝操作的測試結果，供呼叫案例斷言。

            Exceptions:
                sqlite3.OperationalError: 操作失敗所產生的例外。 若由下列處理流程捕捉，則依其轉換規則處理。

            Example:
                在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
                對應測試或輔助流程：test_auth.AuthTests.test_member_and_session_creation_roll_back_together。
            """
            if table == 'login_sessions':
                raise sqlite3.OperationalError('simulated write failure')
            return insert(tx, table, values)
        with patch('app.services.oauth.OAuthService.authenticate', return_value={'id': '123', 'name': 'test'}):
            with patch.object(SQLSession, 'insert', fail_session):
                with self.assertRaises(sqlite3.OperationalError):
                    self.callback(state)
        db = self.app.extensions['sql']
        self.assertEqual(db.select('member'), [])
        self.assertEqual(db.select('login_sessions'), [])
        self.assertFalse(self.client.get('/api/auth/session').json['authenticated'])

    def test_profile_requires_session_and_only_returns_own_member(self):
        """Require authentication and ignore attempts to request another member's profile.
        驗證個人資料須登入且只回傳本人資料。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_profile_requires_session_and_only_returns_own_member。
        """
        self.assertEqual(self.client.get('/api/auth/profile').status_code, 401)
        with patch('app.services.oauth.OAuthService.authenticate', return_value={'id': '123', 'username': 'alice', 'name': 'Alice'}):
            self.callback(self.start())
        db = self.app.extensions['sql']
        db.insert('member', {'userId': '456', 'username': 'bob', 'displayName': 'Bob',
                             'createdAt': 1, 'lastLoginAt': 1})
        response = self.client.get('/api/auth/profile?user_id=456')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(response.json['member']['user_id'], '123')
        self.assertEqual(set(response.json['member']), {'user_id', 'username', 'display_name', 'created_at', 'last_login_at', 'global_name', 'nickname', 'avatar_url', 'guild_joined_at', 'access_role', 'role_ids', 'roles_updated_at'})
        csrf = self.client.get('/api/auth/session').json['csrf_token']
        self.client.post('/api/auth/logout', headers={'X-CSRF-Token': csrf})
        self.assertEqual(self.client.get('/api/auth/profile').status_code, 401)

    def test_profile_rejects_expired_session_and_handles_missing_record(self):
        """Distinguish a missing member record from an expired login.
        驗證個人資料拒絕過期登入並處理缺少紀錄。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_profile_rejects_expired_session_and_handles_missing_record。
        """
        with patch('app.services.oauth.OAuthService.authenticate', return_value={'id': '123', 'name': 'Alice'}):
            self.callback(self.start())
        db = self.app.extensions['sql']
        db.delete('member', {'userId': '123'})
        self.assertEqual(self.client.get('/api/auth/profile').status_code, 401)
        db.execute('UPDATE login_sessions SET expires=0')
        self.assertEqual(self.client.get('/api/auth/profile').status_code, 401)

    def test_stored_avatar_used_by_header_and_profile(self):
        """Verify the session header and profile use the same persisted avatar.
        驗證頁首與個人資料使用儲存的頭像。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_stored_avatar_used_by_header_and_profile。
        """
        user = {'id': '123', 'name': 'Name', 'username': 'name',
                'avatar_url': 'https://cdn.discordapp.com/embed/avatars/0.png',
                'global_name': 'Global', 'nickname': 'Nick', 'guild_joined_at': '2020-01-01T00:00:00+00:00'}
        with patch('app.services.oauth.OAuthService.authenticate', return_value=user):
            self.callback(self.start())
        db = self.app.extensions['sql']
        db.update('member', {'avatarUrl': 'https://cdn.discordapp.com/embed/avatars/1.png'}, {'userId': '123'})
        profile = self.client.get('/api/auth/profile').json['member']
        header = self.client.get('/api/auth/session').json['user']
        self.assertEqual(header['avatar_url'], profile['avatar_url'])
        self.assertTrue(header['avatar_url'].endswith('1.png'))
        self.assertEqual(profile['nickname'], 'Nick')

    def test_legacy_member_schema_upgraded_without_data_loss(self):
        """Upgrade older member tables while preserving their creation timestamps.
        驗證舊成員結構升級不遺失資料。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_legacy_member_schema_upgraded_without_data_loss。
        """
        db = self.app.extensions['sql']
        db.execute('CREATE TABLE member (user_id TEXT PRIMARY KEY, username TEXT, display_name TEXT, created_at REAL NOT NULL, last_login_at REAL NOT NULL)')
        db.insert('member', {'user_id': '123', 'username': 'old', 'created_at': 1, 'last_login_at': 1})
        with patch('app.services.oauth.OAuthService.authenticate', return_value={'id': '123', 'name': 'Updated', 'avatar_url': 'avatar'}):
            self.callback(self.start())
        row = db.select('member')[0]
        self.assertEqual(row['createdAt'], 1)
        self.assertEqual(row['avatarUrl'], 'avatar')
        self.assertEqual(len(db.select('member')), 1)

    def test_full_legacy_profile_migrates_on_read(self):
        """Preserve all legacy values and API keys across repeated read migrations.
        驗證讀取時完整遷移舊個人資料欄位。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_auth.py"
            對應測試或輔助流程：test_auth.AuthTests.test_full_legacy_profile_migrates_on_read。
        """
        from app.models.member import get_member, PROFILE_COLUMNS
        db = self.app.extensions['sql']
        db.execute('''CREATE TABLE member (
            user_id TEXT PRIMARY KEY NOT NULL, username TEXT, display_name TEXT,
            created_at REAL NOT NULL, last_login_at REAL NOT NULL,
            global_name TEXT, nickname TEXT, avatar_url TEXT, guild_joined_at TEXT
        )''')
        original = dict(zip(PROFILE_COLUMNS, (
            '123456789012345678', 'alice', 'Alice', 1.0, 2.0,
            'Global', None, 'https://example.com/avatar.png', '2020-01-01',
        )))
        db.insert('member', original)
        self.assertEqual(get_member(db, original['user_id']), {**original, 'role_ids': [], 'roles_updated_at': None})
        self.assertEqual(get_member(db, original['user_id']), {**original, 'role_ids': [], 'roles_updated_at': None})
        self.assertEqual(db.select('member'), [
            {**{column: original[key] for key, column in PROFILE_COLUMNS.items()}, 'roleIds': None, 'rolesUpdatedAt': None}
        ])
        self.assertIsNone(get_member(db, 'missing'))
