"""Exercise normalized sessions, live administration checks, and permission refresh."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from app import create_app
from app.api.auth import database, digest
from app.models.member import record_login
from app.services.discord import DiscordError

ADMIN = '1555051124334137468'
MEMBER = '578156037589172244'


class AdminTests(unittest.TestCase):
    """Use isolated databases and mock only Discord network operations."""

    def setUp(self):
        """Seed two registered members and one authenticated web administrator."""
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test',
            'SQL_DATABASE_PATH': str(Path(self.temp.name) / 'db.sqlite3'),
            'DISCORD_CACHE_PATH': str(Path(self.temp.name) / 'cache'),
            'DISCORD_BOT_TOKEN': 'test'})
        self.db = self.app.extensions['sql']
        self.service = self.app.extensions['discord']
        with self.app.app_context():
            database()
        with self.db.transaction() as tx:
            for user_id, role in [('111', ADMIN), ('222', MEMBER)]:
                record_login(tx, {'id': user_id, 'name': user_id, 'role_ids': [role]}, 1)
                tx.insert('login_sessions', {'id': digest(user_id), 'userId': user_id, 'expires': time.time() + 3600})
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['login_id'] = '111'
            session['csrf'] = 'test'
        self.live = {'user': {'id': '111'}, 'roles': [ADMIN]}

    def test_authorization_and_csrf(self):
        """Reject anonymous, missing-CSRF, revoked, and unverifiable administrator requests."""
        self.assertEqual(self.app.test_client().post('/api/admin/sync').status_code, 401)
        with patch.object(self.service, '_request') as network:
            self.assertEqual(self.client.post('/api/admin/sync').status_code, 403)
            network.assert_not_called()
        with patch.object(self.service, '_request', return_value={'user': {'id': '111'}, 'roles': [MEMBER]}):
            self.assertEqual(self.client.get('/api/admin/status').status_code, 403)
        with patch.object(self.service, '_request', side_effect=DiscordError('unavailable')):
            self.assertEqual(self.client.get('/api/admin/status').status_code, 502)

    def test_sync_updates_cache_and_revokes_departed_sessions(self):
        """Refresh actual cache files and stored roles without registering new guild users."""
        members = [self.live, {'user': {'id': '333'}, 'roles': [MEMBER]}]
        with patch.object(self.service, '_request', return_value=self.live), patch.object(
                self.service, '_fetch', side_effect=[[{'id': ADMIN}], members]):
            response = self.client.post('/api/admin/sync', headers={'X-CSRF-Token': 'test'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['updatedMembers'], 2)
        self.assertEqual(response.json['revokedSessions'], 1)
        self.assertEqual(len(self.db.select('member')), 2)
        self.assertEqual(json.loads(self.db.select('member', {'userId': '222'})[0]['roleIds']), [])
        self.assertEqual(self.db.select('login_sessions')[0]['userId'], '111')
        self.assertEqual(len(list(self.service.cache_path.glob('*.json'))), 2)

    def test_upstream_failure_preserves_permissions(self):
        """Never clear member roles when fetching the guild fails."""
        before = self.db.select('member')
        with patch.object(self.service, '_request', return_value=self.live), patch.object(
                self.service, '_fetch', side_effect=DiscordError('unavailable')):
            self.assertEqual(self.client.post('/api/admin/sync', headers={'X-CSRF-Token': 'test'}).status_code, 502)
        self.assertEqual(self.db.select('member'), before)

    def test_session_reads_member_changes_immediately(self):
        """Identity and permissions come from member, not per-session snapshots."""
        self.db.update('member', {'displayName': 'Updated', 'roleIds': json.dumps([MEMBER])}, {'userId': '111'})
        user = self.client.get('/api/auth/session').json['user']
        self.assertEqual(user['name'], 'Updated')
        self.assertEqual(user['access_role']['key'], 'member')
        self.assertEqual(set(self.db.select('login_sessions')[0]), {'id', 'userId', 'expires'})

    def test_legacy_session_migration_is_idempotent(self):
        """Retain valid linked sessions and newest role snapshot without overwriting profiles."""
        self.db.execute('DROP TABLE login_sessions')
        self.db.execute('CREATE TABLE login_sessions (id TEXT PRIMARY KEY, user TEXT NOT NULL, expires REAL NOT NULL)')
        self.db.update('member', {'roleIds': None}, {'userId': '111'})
        for token, user_id, roles, expires in [('111', '111', [ADMIN], time.time() + 3600),
                ('older', '111', [MEMBER], time.time() + 1800), ('missing', '999', [ADMIN], time.time() + 3600)]:
            self.db.insert('login_sessions', {'id': digest(token), 'user': json.dumps({'id': user_id, 'role_ids': roles}), 'expires': expires})
        with self.app.app_context():
            database()
            database()
        self.assertEqual(len(self.db.select('login_sessions')), 2)
        self.assertEqual(self.db.query('PRAGMA foreign_key_check'), [])
        self.assertEqual(self.client.get('/api/auth/session').json['user']['access_role']['key'], 'web_admin')
