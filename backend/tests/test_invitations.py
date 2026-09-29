"""Verify invitation settings, live administrator validation, and click-only attribution."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import uuid

from app import create_app
from app.models.invitation import ROLES, ensure_schema, record_click
from app.services.discord import DiscordError
from app.sql import SQLSession


class InvitationTests(unittest.TestCase):
    """Use isolated SQLite data and mocked Discord membership without real invites."""
    def setUp(self):
        """Prepare an anonymous browser and an isolated application database."""
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'invitation-test',
            'SQL_DATABASE_PATH': str(Path(self.temp.name) / 'invitations.sqlite3'),
            'DISCORD_BOT_TOKEN': 'test-token'})
        self.client = self.app.test_client()
        self.db = self.app.extensions['sql']
        self.service = self.app.extensions['discord']
        self.settings = self.client.get('/api/invitations').json
        self.admin = {'user': {'id': '12345', 'username': 'lightinvi'},
                      'roles': ['513295891482804250']}

    def click(self, role=ROLES[0], code='', request_id=None):
        """Post one browser-authenticated click with a stable optional retry identifier."""
        return self.client.post('/api/invitations/click',
            headers={'X-CSRF-Token': self.settings['csrf_token']},
            json={'role': role, 'administrator_code': code,
                  'request_id': request_id or str(uuid.uuid4())})

    def test_defaults_and_protected_url_not_exposed(self):
        """Seed the three requested options while keeping raw invite codes out of GET."""
        self.assertEqual([item['role'] for item in self.settings['invitations']], list(ROLES))
        self.assertEqual([row['code'] for row in self.db.select('invitation_url', order_by='rowid')],
                         ['rnTHPNfjMx', 'HgtKZUX72K', 'UDNkUgQ4Yy'])
        self.assertNotIn('UDNkUgQ4Yy', str(self.settings))
        self.assertEqual(self.settings['invitations'][2]['requiresCode'], True)

    def test_guest_and_member_clicks_are_not_joins(self):
        """Record separate clicks without inventing Discord join status or referrers."""
        for role, code in ((ROLES[0], 'rnTHPNfjMx'), (ROLES[1], 'HgtKZUX72K')):
            result = self.click(role, 'untrusted-referrer')
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json['url'], f'https://discord.com/invite/{code}')
        for row in self.db.select('invitation_record'):
            self.assertEqual(row['eventType'], 'click')
            self.assertIsNone(row['administratorId'])
            self.assertIsNone(row['administratorUsername'])
            self.assertGreater(row['clickedAt'], 0)

    def test_regular_click_records_live_administrator_identity(self):
        """Resolve an administrator username and preserve both stable ID and username."""
        with patch.object(self.service, '_fetch', return_value=[self.admin]) as fetch:
            response = self.click(ROLES[2], ' LightInVi ')
        self.assertEqual(response.status_code, 200)
        fetch.assert_called_once_with('members')
        row = self.db.select('invitation_record')[0]
        self.assertEqual(row['administratorId'], '12345')
        self.assertEqual(row['administratorUsername'], 'lightinvi')
        self.assertEqual(row['invitationCode'], 'UDNkUgQ4Yy')

    def test_invalid_regular_codes_and_nonadministrators_rejected(self):
        """Reject missing codes, non-admin users, bots, and pending guild members."""
        self.assertEqual(self.click(ROLES[2]).status_code, 400)
        cases = [[], [{**self.admin, 'roles': []}],
                 [{**self.admin, 'user': {**self.admin['user'], 'bot': True}}],
                 [{**self.admin, 'pending': True}]]
        for members in cases:
            with self.subTest(members=members), patch.object(self.service, '_fetch', return_value=members):
                response = self.click(ROLES[2], 'lightinvi')
                self.assertEqual(response.status_code, 400)
                self.assertNotIn('url', response.json)
        self.assertEqual(self.db.select('invitation_record'), [])

    def test_discord_outage_does_not_record_or_release_link(self):
        """Fail closed when live administrator validation cannot complete."""
        with patch.object(self.service, '_fetch', side_effect=DiscordError('private-detail')):
            response = self.click(ROLES[2], 'lightinvi')
        self.assertEqual(response.status_code, 502)
        self.assertNotIn('private-detail', response.get_data(as_text=True))
        self.assertEqual(self.db.select('invitation_record'), [])

    def test_database_updates_take_effect_without_reseeding(self):
        """Read changed descriptions and codes immediately while retaining old history."""
        self.click()
        self.db.update('invitation_url', {'code': 'newGuest', 'description': '更新的描述'}, {'role': ROLES[0]})
        response = self.client.get('/api/invitations')
        self.assertEqual(response.json['invitations'][0]['description'], '更新的描述')
        self.assertEqual(self.click().json['url'], 'https://discord.com/invite/newGuest')
        self.assertEqual(self.db.select('invitation_record', order_by='id')[0]['invitationCode'], 'rnTHPNfjMx')
        self.db.delete('invitation_url', {'role': ROLES[0]})
        self.client.get('/api/invitations')
        self.assertEqual(self.db.select('invitation_url', {'role': ROLES[0]}), [])
        self.assertEqual(self.click().status_code, 410)

    def test_expired_invites_are_disabled_and_rejected(self):
        """Reject direct clicks after an administrator marks a displayed invite expired."""
        self.db.update('invitation_url', {'isExpired': 1}, {'role': ROLES[0]})
        self.assertTrue(self.client.get('/api/invitations').json['invitations'][0]['isExpired'])
        self.assertEqual(self.click().status_code, 410)
        self.assertEqual(self.db.select('invitation_record'), [])

    def test_invalid_input_and_missing_csrf_never_record(self):
        """Require a browser token and valid identifiers before any attribution writes."""
        self.assertEqual(self.client.post('/api/invitations/click', json={}).status_code, 403)
        self.assertEqual(self.click('unknown').status_code, 400)
        self.assertEqual(self.click(request_id='invalid').status_code, 400)
        self.db.update('invitation_url', {'code': 'https://evil.example'}, {'role': ROLES[0]})
        self.assertEqual(self.click().status_code, 410)
        self.assertEqual(self.db.select('invitation_record'), [])

    def test_retries_count_once_but_new_clicks_count_again(self):
        """Make request retries idempotent without suppressing subsequent deliberate clicks."""
        request_id = str(uuid.uuid4())
        first = self.click(request_id=request_id)
        self.assertEqual(self.click(request_id=request_id).json, first.json)
        self.click()
        self.assertEqual(len(self.db.select('invitation_record')), 2)

    def test_concurrent_initialization_and_retry_are_atomic(self):
        """Prevent concurrent workers from duplicating defaults or one click record."""
        request_id = str(uuid.uuid4())
        def save(_):
            """Initialize schema and replay the same browser action from another worker."""
            ensure_schema(self.db)
            return record_click(self.db, ROLES[0], 'same-browser', request_id)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(save, range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(self.db.select('invitation_record')), 1)
        self.assertEqual(len(self.db.select('invitation_url')), 3)

    def test_failed_record_write_never_returns_redirect(self):
        """Require a committed audit record before releasing the Discord URL."""
        insert = SQLSession.insert
        def fail_record(tx, table, values):
            """Simulate a write failure for the click record only."""
            if table == 'invitation_record':
                raise sqlite3.OperationalError('simulated failure')
            return insert(tx, table, values)
        with patch.object(SQLSession, 'insert', fail_record):
            with self.assertLogs(self.app.logger, level='ERROR'):
                response = self.click()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('url', response.json)
        self.assertEqual(self.db.select('invitation_record'), [])

    def test_legacy_columns_migrate_without_losing_history_or_constraints(self):
        """Rename legacy columns once while retaining snapshots and retry semantics."""
        request_id = str(uuid.uuid4())
        with self.db.transaction() as tx:
            tx.execute('DROP TABLE invitation_record')
            tx.execute('''CREATE TABLE invitation_record (
                id INTEGER PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                visitor_id TEXT NOT NULL,
                invitation_code TEXT NOT NULL,
                role TEXT NOT NULL,
                administrator_id TEXT,
                administrator_username TEXT,
                clicked_at REAL NOT NULL,
                event_type TEXT NOT NULL DEFAULT 'click' CHECK (event_type = 'click')
            )''')
            tx.insert('invitation_record', {
                'id': 42, 'request_id': request_id, 'visitor_id': 'browser',
                'invitation_code': 'UDNkUgQ4Yy', 'role': ROLES[2],
                'administrator_id': '12345', 'administrator_username': 'lightinvi',
                'clicked_at': 123456.0, 'event_type': 'click',
            })
        ensure_schema(self.db)
        ensure_schema(self.db)
        expected = {
            'id': 42, 'requestId': request_id, 'visitorId': 'browser',
            'invitationCode': 'UDNkUgQ4Yy', 'role': ROLES[2],
            'administratorId': '12345', 'administratorUsername': 'lightinvi',
            'clickedAt': 123456.0, 'eventType': 'click',
        }
        self.assertEqual(self.db.select('invitation_record'), [expected])
        retry = record_click(self.db, ROLES[2], 'browser', request_id, self.admin['user'])
        self.assertEqual(retry, {'id': 42, 'code': 'UDNkUgQ4Yy'})
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.insert('invitation_record', {**expected, 'id': 43})
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.insert('invitation_record', {
                **expected, 'id': 43, 'requestId': str(uuid.uuid4()), 'eventType': 'join',
            })
        self.assertEqual(self.click().status_code, 200)
        self.assertEqual(len(self.db.select('invitation_record')), 2)

    def test_cli_changes_and_disables_settings(self):
        """Let an operator edit persisted settings without rebuilding the frontend."""
        runner = self.app.test_cli_runner()
        result = runner.invoke(args=['invitations', 'set', '--role', ROLES[0], '--code', 'edited',
                                     '--description', '新的介紹', '--expired'])
        self.assertEqual(result.exit_code, 0, result.output)
        row = self.db.select('invitation_url', {'role': ROLES[0]})[0]
        self.assertEqual((row['code'], row['description'], row['isExpired']), ('edited', '新的介紹', 1))
        result = runner.invoke(args=['invitations', 'set', '--role', ROLES[0], '--code', 'https://bad.example'])
        self.assertNotEqual(result.exit_code, 0)
