"""Verify UUID migration preserves ledger order, references, retries, and constraints."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from app import create_app
from app.models.member import record_login
from app.models.record_ids import migrate_record_ids, new_record_id
from app.models.star_shard import append_entry, balance, ensure_schema, transfer
from app.models.daily_spinner import spin
from app.models.invitation import ROLES, InvitationError, ensure_schema as ensure_invitations, record_click
from app.sql import SQLSession


class RecordIdTests(unittest.TestCase):
    """Start with colliding integer IDs in legacy tables and test a complete upgrade."""

    def setUp(self):
        """Build the previous schema and seed an award, a transfer, and an invite click."""
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        app = create_app({'TESTING': True, 'SECRET_KEY': 'uuid-test',
            'SQL_DATABASE_PATH': str(Path(self.temp.name) / 'legacy.sqlite3')})
        self.db = app.extensions['sql']
        self.spin_request = str(uuid4())
        self.transfer_request = str(uuid4())
        self.invite_request = str(uuid4())
        with self.db.transaction(immediate=True) as tx:
            for user_id in ('111', '222'):
                record_login(tx, {'id': user_id, 'username': user_id}, 1)
            tx.execute('''CREATE TABLE daily_spinner (
                id INTEGER PRIMARY KEY AUTOINCREMENT, userId TEXT NOT NULL REFERENCES member(userId),
                spinDate TEXT NOT NULL, requestId TEXT NOT NULL, multiplier REAL NOT NULL,
                baseReward INTEGER NOT NULL, reward INTEGER NOT NULL, createdAt REAL NOT NULL,
                UNIQUE(userId, spinDate), UNIQUE(userId, requestId))''')
            tx.execute('''CREATE TABLE star_shard (
                id INTEGER PRIMARY KEY AUTOINCREMENT, userId TEXT NOT NULL REFERENCES member(userId),
                amount INTEGER NOT NULL, beforeBlance INTEGER NOT NULL, afterBlance INTEGER NOT NULL,
                transactionType TEXT NOT NULL, transactionSource TEXT NOT NULL,
                description TEXT NOT NULL, createdAt REAL NOT NULL,
                CHECK(afterBlance = beforeBlance + amount))''')
            tx.execute('''CREATE TABLE star_shard_request (
                userId TEXT NOT NULL, requestId TEXT NOT NULL, recipientId TEXT NOT NULL,
                amount INTEGER NOT NULL, debitId INTEGER NOT NULL REFERENCES star_shard(id),
                creditId INTEGER NOT NULL REFERENCES star_shard(id), PRIMARY KEY(userId, requestId))''')
            tx.execute('''CREATE TABLE invitation_record (
                id INTEGER PRIMARY KEY, requestId TEXT NOT NULL UNIQUE, visitorId TEXT NOT NULL,
                invitationCode TEXT NOT NULL, role TEXT NOT NULL, administratorId TEXT,
                administratorUsername TEXT, clickedAt REAL NOT NULL,
                eventType TEXT NOT NULL DEFAULT 'click' CHECK(eventType = 'click'))''')
            tx.insert('daily_spinner', {'id': 1, 'userId': '111', 'spinDate': '2026-01-01',
                'requestId': self.spin_request, 'multiplier': 1, 'baseReward': 10, 'reward': 10, 'createdAt': 100})
            tx.insert('invitation_record', {'id': 1, 'requestId': self.invite_request,
                'visitorId': 'browser', 'invitationCode': 'rnTHPNfjMx', 'role': ROLES[0], 'clickedAt': 100})
            for record_id, user, amount, before, after, kind, source in (
                (1, '111', 10, 0, 10, 'daily_spinner', '1'),
                (2, '111', -3, 10, 7, 'transaction', '222'),
                (3, '222', 3, 0, 3, 'transaction', '111'),
            ):
                tx.insert('star_shard', {'id': record_id, 'userId': user, 'amount': amount,
                    'beforeBlance': before, 'afterBlance': after, 'transactionType': kind,
                    'transactionSource': source, 'description': 'history', 'createdAt': 100})
            tx.insert('star_shard_request', {'userId': '111', 'requestId': self.transfer_request,
                'recipientId': '222', 'amount': 3, 'debitId': 2, 'creditId': 3})
            for table in ('daily_spinner', 'star_shard'):
                for operation in ('UPDATE', 'DELETE'):
                    tx.execute(f'''CREATE TRIGGER {table}_no_{operation.lower()}
                        BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'immutable'); END''')
        self.before = {table: self.db.select(table) for table in (
            'star_shard', 'daily_spinner', 'star_shard_request', 'invitation_record')}

    def migrate(self):
        """Run the same locked migration used by every record-writing feature."""
        with self.db.transaction(immediate=True) as tx:
            migrate_record_ids(tx)

    def test_migration_preserves_all_references_and_history(self):
        """Convert colliding IDs to unique UUIDs while retaining balances and external IDs."""
        self.migrate()
        ledger = self.db.select('star_shard', order_by='sequence')
        spinner = self.db.select('daily_spinner')[0]
        invitation = self.db.select('invitation_record')[0]
        receipt = self.db.select('star_shard_request')[0]
        ids = [row['id'] for row in ledger] + [spinner['id'], invitation['id']]
        self.assertEqual(len(set(ids)), 5)
        self.assertTrue(all(UUID(value).version == 4 for value in ids))
        self.assertEqual(ledger[0]['transactionSource'], spinner['id'])
        self.assertEqual((receipt['debitId'], receipt['creditId']), (ledger[1]['id'], ledger[2]['id']))
        self.assertEqual([row['transactionSource'] for row in ledger[1:]], ['222', '111'])
        for old, new in zip(self.before['star_shard'], ledger):
            for field in ('userId', 'amount', 'beforeBlance', 'afterBlance', 'createdAt', 'description'):
                self.assertEqual(old[field], new[field])
        self.assertEqual((balance(self.db, '111'), balance(self.db, '222')), (7, 3))
        self.assertEqual(self.db.query('PRAGMA foreign_key_check'), [])
        self.assertEqual(transfer(self.db, '111', '222', 3, self.transfer_request)['recordId'], ledger[1]['id'])
        self.assertEqual(spin(self.db, '111', self.spin_request)['result']['id'], spinner['id'])
        ensure_invitations(self.db)
        with self.assertRaises(InvitationError) as expired:
            record_click(self.db, ROLES[0], 'browser', self.invite_request)
        self.assertEqual(expired.exception.status, 410)
        self.migrate()
        self.assertEqual(self.db.select('star_shard', order_by='sequence'), ledger)

    def test_migration_failure_rolls_back_original_schema_and_data(self):
        """Rollback all tables and original triggers if copying any related receipt fails."""
        insert = SQLSession.insert
        def fail_receipt(tx, table, values):
            """Simulate a failure after the parent tables have been rebuilt."""
            if table == 'star_shard_request':
                raise sqlite3.OperationalError('simulated failure')
            return insert(tx, table, values)
        with patch.object(SQLSession, 'insert', fail_receipt), self.assertRaises(sqlite3.OperationalError):
            self.migrate()
        for table, original in self.before.items():
            self.assertEqual(self.db.select(table), original)
        self.assertEqual(self.db.query('PRAGMA table_info(star_shard)')[0]['type'], 'INTEGER')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.delete('star_shard', {'id': 1})
        self.migrate()

    def test_migrated_constraints_and_foreign_keys_remain_active(self):
        """Preserve append-only guards, references, and once-per-day reward uniqueness."""
        self.migrate()
        ledger = self.db.select('star_shard')[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.delete('star_shard', {'id': ledger['id']})
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.update('daily_spinner', {'reward': 50}, {'userId': '111'})
        spinner = self.db.select('daily_spinner')[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.insert('daily_spinner', {**spinner, 'id': new_record_id(), 'requestId': str(uuid4())})
        receipt = self.db.select('star_shard_request')[0]
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.insert('star_shard_request', {**receipt, 'requestId': str(uuid4()), 'debitId': new_record_id()})

    def test_concurrent_migrations_do_not_regenerate_ids(self):
        """Multiple workers observe the same final UUIDs after a single migration."""
        def migrate_and_read(_):
            """Enter the migration from a separate connection and read stable IDs."""
            self.migrate()
            return self.db.select('star_shard', order_by='sequence')
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(migrate_and_read, range(4)))
        self.assertTrue(all(rows == results[0] for rows in results))

    def test_balance_order_is_independent_of_uuid_and_clock(self):
        """Use commit sequence even when UUIDs and wall-clock timestamps decrease."""
        self.migrate()
        with self.db.transaction(immediate=True) as tx:
            ensure_schema(tx)
            with patch('app.models.star_shard.new_record_id', return_value='ffffffff-ffff-4fff-bfff-ffffffffffff'):
                append_entry(tx, '111', 1, 'test', 'event-a', 'first')
            with patch('app.models.star_shard.new_record_id', return_value='00000000-0000-4000-8000-000000000001'), patch('app.models.star_shard.time.time', return_value=1):
                append_entry(tx, '111', 2, 'test', 'event-b', 'second')
            self.assertEqual(balance(tx, '111'), 10)

    def test_unknown_foreign_references_fail_without_data_loss(self):
        """Require an explicit migration for future dependent tables rather than guessing."""
        self.db.execute('CREATE TABLE future_relation (recordId INTEGER REFERENCES star_shard(id))')
        with self.assertRaises(sqlite3.IntegrityError):
            self.migrate()
        self.assertEqual(self.db.select('star_shard'), self.before['star_shard'])
