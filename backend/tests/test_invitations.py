"""Verify invitation settings, live administrator validation, and click-only attribution."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import uuid

from app import create_app
from app.models.invitation import ROLES, InvitationError, ensure_schema, record_click
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
        self.invites = patch.object(self.service, 'create_invite', return_value='dynamicCode').start()
        self.addCleanup(patch.stopall)
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
        self.assertNotIn('invitation_url', self.db.list_tables())
        self.assertEqual(self.settings['invitations'][2]['requiresCode'], True)

    def test_guest_and_member_clicks_are_not_joins(self):
        """Record separate clicks without inventing Discord join status or referrers."""
        for role, code in ((ROLES[0], 'dynamicCode'), (ROLES[1], 'dynamicCode')):
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
        self.assertEqual(row['invitationCode'], 'dynamicCode')

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

    def test_static_table_removed_without_losing_history(self):
        self.click()
        history = self.db.select('invitation_record')
        self.db.execute('CREATE TABLE invitation_url (code TEXT)')
        self.db.insert('invitation_url', {'code': 'oldCode'})
        ensure_schema(self.db)
        ensure_schema(self.db)
        self.assertNotIn('invitation_url', self.db.list_tables())
        self.assertEqual(self.db.select('invitation_record'), history)

    def test_expired_retry_rejected(self):
        request_id = str(uuid.uuid4())
        self.click(request_id=request_id)
        with patch('app.models.invitation.time.time', return_value=self.db.select('invitation_record')[0]['clickedAt'] + 600):
            self.assertEqual(self.click(request_id=request_id).status_code, 410)
        self.invites.assert_called_once()

    def test_creation_failure_has_no_record(self):
        self.invites.side_effect = DiscordError('Discord unavailable', 503, 12)
        response = self.click()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers['Retry-After'], '12')
        self.assertEqual(self.db.select('invitation_record'), [])

    def test_invalid_input_and_missing_csrf_never_record(self):
        """Require a browser token and valid identifiers before any attribution writes."""
        self.assertEqual(self.client.post('/api/invitations/click', json={}).status_code, 403)
        self.assertEqual(self.click('unknown').status_code, 400)
        self.assertEqual(self.click(request_id='invalid').status_code, 400)
        self.assertEqual(self.db.select('invitation_record'), [])

    def test_retries_and_new_clicks_reuse_visitor_invite(self):
        """Different request IDs from one visitor must not generate additional invites."""
        request_id = str(uuid.uuid4())
        first = self.click(request_id=request_id)
        self.assertEqual(self.click(request_id=request_id).json, first.json)
        self.assertEqual(self.click().json, first.json)
        self.assertEqual(len(self.db.select('invitation_record')), 1)
        self.invites.assert_called_once()

    def test_expiry_uses_original_creation_time(self):
        first = self.click()
        created = self.db.select('invitation_record')[0]['clickedAt']
        with patch('app.models.invitation.time.time', return_value=created + 599):
            self.assertEqual(self.click().json, first.json)
        self.invites.return_value = 'newCode'
        with patch('app.models.invitation.time.time', return_value=created + 600):
            second = self.click()
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json['url'], 'https://discord.com/invite/newCode')
        self.assertNotEqual(first.json['record_id'], second.json['record_id'])
        self.assertEqual(self.invites.call_count, 2)
        self.assertEqual(len(self.db.select('invitation_record')), 2)

    def test_other_visitor_gets_separate_invitation(self):
        record_click(self.db, ROLES[0], 'visitor-a', str(uuid.uuid4()), discord=self.service)
        record_click(self.db, ROLES[0], 'visitor-b', str(uuid.uuid4()), discord=self.service)
        self.assertEqual(self.invites.call_count, 2)

    def test_changed_role_gets_separate_invitation(self):
        self.invites.side_effect = ['regularCode', 'guestCode', 'memberCode']
        with patch.object(self.service, '_fetch', return_value=[self.admin]):
            regular = self.click(ROLES[2], 'lightinvi')
        guest = self.click(ROLES[0])
        member = self.click(ROLES[1])
        self.assertEqual(regular.json['url'], 'https://discord.com/invite/regularCode')
        self.assertEqual(guest.json['url'], 'https://discord.com/invite/guestCode')
        self.assertEqual(member.json['url'], 'https://discord.com/invite/memberCode')
        self.assertEqual(self.click(ROLES[0]).json, guest.json)
        self.assertEqual(self.click(ROLES[1]).json, member.json)
        with patch.object(self.service, '_fetch', return_value=[self.admin]):
            self.assertEqual(self.click(ROLES[2], 'lightinvi').json, regular.json)
        rows = self.db.select('invitation_record')
        self.assertEqual(len(rows), 3)
        self.assertEqual(next(row for row in rows if row['role'] == ROLES[2])['administratorId'], '12345')
        self.assertEqual(self.invites.call_count, 3)

    def test_concurrent_distinct_clicks_generate_one_visitor_invite(self):
        def save(_):
            return record_click(self.db, ROLES[0], 'same-browser', str(uuid.uuid4()), discord=self.service)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(save, range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(self.db.select('invitation_record')), 1)
        self.invites.assert_called_once()

    def test_concurrent_initialization_and_retry_are_atomic(self):
        """Prevent concurrent workers from duplicating defaults or one click record."""
        request_id = str(uuid.uuid4())
        def save(_):
            """Initialize schema and replay the same browser action from another worker."""
            ensure_schema(self.db)
            return record_click(self.db, ROLES[0], 'same-browser', request_id, discord=self.service)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(save, range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(self.db.select('invitation_record')), 1)
        self.invites.assert_called_once()

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
        migrated_id = self.db.select('invitation_record')[0]['id']
        self.assertEqual(uuid.UUID(migrated_id).version, 4)
        expected = {
            'id': migrated_id, 'requestId': request_id, 'visitorId': 'browser',
            'invitationCode': 'UDNkUgQ4Yy', 'role': ROLES[2],
            'administratorId': '12345', 'administratorUsername': 'lightinvi',
            'clickedAt': 123456.0, 'eventType': 'click',
        }
        self.assertEqual(self.db.select('invitation_record'), [expected])
        with self.assertRaises(InvitationError) as expired:
            record_click(self.db, ROLES[2], 'browser', request_id, self.admin['user'])
        self.assertEqual(expired.exception.status, 410)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.insert('invitation_record', {**expected, 'id': 43})
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.insert('invitation_record', {
                **expected, 'id': 43, 'requestId': str(uuid.uuid4()), 'eventType': 'join',
            })
        self.assertEqual(self.click().status_code, 200)
        self.assertEqual(len(self.db.select('invitation_record')), 2)
