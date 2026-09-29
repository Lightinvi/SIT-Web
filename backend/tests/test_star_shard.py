"""Exercise authenticated ledger reads, atomic transfers, and concurrent retries."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

from app import create_app
from app.api.auth import database, digest
from app.models.member import record_login
from app.models.star_shard import append_entry, balance, ensure_schema, ShardError, transfer
from app.sql import SQLSession


class StarShardTests(unittest.TestCase):
    """Use temporary databases and real signed sessions without contacting Discord."""

    def setUp(self):
        """Create two registered accounts and a server-side session for the sender."""
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test',
            'SQL_DATABASE_PATH': str(Path(self.temp.name) / 'test.sqlite3')})
        self.db = self.app.extensions['sql']
        with self.app.app_context():
            database()
        with self.db.transaction(immediate=True) as tx:
            for user_id in ('111', '222'):
                record_login(tx, {'id': user_id, 'username': 'member' + user_id, 'name': user_id}, 1)
            ensure_schema(tx)
        self.client = self.app.test_client()
        self.db.insert('login_sessions', {'id': digest('login'), 'user': json.dumps({'id': '111'}), 'expires': time.time() + 1000})
        with self.client.session_transaction() as session:
            session['login_id'] = 'login'
            session['csrf'] = 'token'

    def credit(self, amount=100):
        """Seed an isolated system reward through the trusted ledger service."""
        with self.db.transaction(immediate=True) as tx:
            append_entry(tx, '111', amount, 'dailyReward', 'daily-test', 'Daily reward')

    def give(self, **overrides):
        """Submit an authenticated transfer with optional validation overrides."""
        return self.client.post('/api/star-shards/transfer', headers={'X-CSRF-Token': 'token'},
            json={'recipientId': '222', 'amount': 30, 'requestId': str(uuid4()), **overrides})

    def test_zero_balance_and_private_access(self):
        """Return zero for new members and deny all routes to anonymous sessions."""
        self.assertEqual(self.client.get('/api/star-shards/balance').json, {'balance': 0})
        anonymous = self.app.test_client()
        for route in ('balance', 'records', 'members'):
            self.assertEqual(anonymous.get('/api/star-shards/' + route).status_code, 401)
        self.assertEqual(anonymous.post('/api/star-shards/transfer', json={}).status_code, 401)
        self.assertEqual(self.client.get('/api/star-shards/balance').headers['Cache-Control'], 'no-store')

    def test_transfer_has_two_balanced_entries(self):
        """Record signed amounts, counterpart IDs, and before/after snapshots."""
        self.credit()
        self.assertEqual(self.give().json['balance'], 70)
        debit, credit = self.db.select('star_shard', order_by='sequence')[1:]
        self.assertEqual((debit['amount'], debit['beforeBlance'], debit['afterBlance']), (-30, 100, 70))
        self.assertEqual((credit['amount'], credit['beforeBlance'], credit['afterBlance']), (30, 0, 30))
        self.assertEqual((debit['transactionSource'], credit['transactionSource']), ('222', '111'))
        self.assertEqual(debit['transactionType'], 'transaction')

    def test_invalid_transfers_and_csrf_leave_no_records(self):
        """Reject self, missing members, overdrafts, malformed amounts, and forged CSRF."""
        self.credit()
        for data in ({'recipientId': '111'}, {'recipientId': 'unknown'}, {'amount': 101},
                     {'amount': 0}, {'amount': -1}, {'amount': True}, {'amount': 1.5},
                     {'amount': '1'}, {'requestId': 'invalid'}, {'amount': 2**53}):
            with self.subTest(data=data):
                self.assertEqual(self.give(**data).status_code, 400)
        self.assertEqual(self.client.post('/api/star-shards/transfer', json={}).status_code, 403)
        self.assertEqual(len(self.db.select('star_shard')), 1)

    def test_retries_are_idempotent_and_payload_is_bound(self):
        """Replay one successful transfer and reject reuse for a different amount."""
        self.credit()
        request_id = str(uuid4())
        first = self.give(requestId=request_id)
        self.assertEqual(self.give(requestId=request_id).json, first.json)
        self.assertEqual(self.give(requestId=request_id, amount=20).status_code, 400)
        self.assertEqual(len(self.db.select('star_shard')), 3)

    def test_concurrent_spending_cannot_overdraw(self):
        """Serialize competing debits so only one can consume the available balance."""
        self.credit()
        def spend(_):
            """Attempt a transfer from an independent database connection."""
            try:
                transfer(self.db, '111', '222', 70, str(uuid4()))
                return True
            except ShardError:
                return False
        with ThreadPoolExecutor(max_workers=4) as executor:
            self.assertEqual(sum(executor.map(spend, range(4))), 1)
        self.assertEqual(balance(self.db, '111'), 30)
        self.assertEqual(balance(self.db, '222'), 70)

    def test_concurrent_retries_write_once(self):
        """Serialize duplicate requests to one paired ledger transaction."""
        self.credit()
        request_id = str(uuid4())
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda _: transfer(self.db, '111', '222', 30, request_id), range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(len(self.db.select('star_shard')), 3)

    def test_credit_failure_rolls_back_debit(self):
        """Rollback both ledger sides when the second insert fails."""
        self.credit()
        insert = SQLSession.insert
        def fail_credit(tx, table, values):
            """Simulate failure specifically while writing the recipient's ledger entry."""
            if table == 'star_shard' and values['userId'] == '222':
                raise sqlite3.OperationalError('write failure')
            return insert(tx, table, values)
        with patch.object(SQLSession, 'insert', fail_credit), self.assertLogs(self.app.logger, level='ERROR'):
            self.assertEqual(self.give().status_code, 503)
        self.assertEqual(balance(self.db, '111'), 100)
        self.assertEqual(self.db.select('star_shard_request'), [])

    def test_cursor_pagination_is_private_and_stable(self):
        """Read 20 then 20 then 5 without overlap despite an intervening credit."""
        for _ in range(45):
            self.credit(1)
        first = self.client.get('/api/star-shards/records?userId=222').json
        self.assertEqual(len(first['records']), 20)
        self.credit(1)
        second = self.client.get(f"/api/star-shards/records?before={first['nextCursor']}").json
        third = self.client.get(f"/api/star-shards/records?before={second['nextCursor']}").json
        self.assertEqual([len(second['records']), len(third['records'])], [20, 5])
        self.assertIsNone(third['nextCursor'])
        rows = first['records'] + second['records'] + third['records']
        self.assertEqual(len({row['id'] for row in rows}), 45)
        self.assertTrue(all(row['userId'] == '111' for row in rows))
        self.assertEqual(self.client.get('/api/star-shards/records?before=bad').status_code, 400)
        self.assertEqual(self.client.get('/api/star-shards/records?before=' + '9' * 5000).status_code, 400)

    def test_expired_session_cannot_spend(self):
        """Reject a previously authenticated sender after server-side expiry."""
        self.credit()
        self.db.update('login_sessions', {'expires': 0}, {'id': digest('login')})
        self.assertEqual(self.give().status_code, 401)
        self.assertEqual(balance(self.db, '111'), 100)

    def test_history_uses_own_uuid_cursors(self):
        """Reject another member's cursor and keep internal sequence numbers private."""
        self.credit()
        self.give()
        rows = self.client.get('/api/star-shards/records').json['records']
        from uuid import UUID
        self.assertTrue(all(UUID(row['id']).version == 4 for row in rows))
        self.assertTrue(all('sequence' not in row for row in rows))
        other = self.db.select('star_shard', {'userId': '222'})[0]['id']
        self.assertEqual(self.client.get(f'/api/star-shards/records?before={other}').status_code, 400)
        page = self.client.get(f"/api/star-shards/records?before={rows[0]['id']}").json
        self.assertEqual([row['id'] for row in page['records']], [rows[1]['id']])

    def test_member_search_and_immutable_ledger(self):
        """Exclude the sender from search and prevent historical balance tampering."""
        self.assertEqual([row['userId'] for row in self.client.get('/api/star-shards/members').json['members']], ['222'])
        self.assertEqual(self.client.get('/api/star-shards/members?q=nomatch').json['members'], [])
        self.credit()
        record_id = self.db.select('star_shard')[0]['id']
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.update('star_shard', {'afterBlance': 99}, {'id': record_id})
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.delete('star_shard', {'id': record_id})
