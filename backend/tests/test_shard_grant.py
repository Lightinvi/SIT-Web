"""Test authorization, atomic system grants, and idempotent retries."""
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_admin
from app.models.shard_grant import grant
from app.models.star_shard import MAX_AMOUNT, append_entry, ensure_schema
from app.sql import SQLSession


class GrantTests(unittest.TestCase):
    """Exercise real ledger writes with mocked live Discord authorization only."""
    setUp = test_admin.AdminTests.setUp

    def post(self, **overrides):
        """Submit one protected system grant with configurable input."""
        return self.client.post('/api/admin/shards/grant', headers={'X-CSRF-Token': 'test'},
            json={'recipientId': '222', 'amount': 50, 'requestId': str(uuid4()), **overrides})

    def test_grant_is_system_income_with_auditable_administrator(self):
        """The server sets ledger type and description regardless of supplied fields."""
        with patch.object(self.service, '_request', return_value=self.live):
            response = self.post(transactionType='cheat', description='cheat', administratorId='222')
        self.assertEqual(response.status_code, 200)
        receipt = response.json['receipt']
        self.assertEqual(receipt['administratorId'], '111')
        row = self.db.select('star_shard')[0]
        self.assertEqual((row['userId'], row['amount'], row['beforeBlance'], row['afterBlance']), ('222', 50, 0, 50))
        self.assertEqual((row['transactionType'], row['description']), ('system', '系統發放'))
        self.assertEqual(row['transactionSource'], receipt['id'])
        self.assertEqual(row['id'], receipt['recordId'])

    def test_only_live_web_admin_with_csrf_can_grant(self):
        """Anonymous, stale role snapshots and forged requests cannot mint shards."""
        self.assertEqual(self.app.test_client().post('/api/admin/shards/grant').status_code, 401)
        self.assertEqual(self.client.post('/api/admin/shards/grant').status_code, 403)
        with patch.object(self.service, '_request', return_value={'user': {'id': '111'}, 'roles': [test_admin.MEMBER]}):
            self.assertEqual(self.post().status_code, 403)
            self.assertEqual(self.client.get('/api/admin/shards/members').status_code, 403)
        self.assertFalse(self.db.table_exists('star_shard'))

    def test_invalid_amount_recipient_and_overflow(self):
        """Reject nonpositive or unsafe amounts and unknown recipient IDs."""
        with patch.object(self.service, '_request', return_value=self.live):
            for amount in (0, -1, True, 1.5, '50', MAX_AMOUNT + 1):
                self.assertEqual(self.post(amount=amount).status_code, 400)
            self.assertEqual(self.post(recipientId='missing').status_code, 400)
            with self.db.transaction() as tx:
                ensure_schema(tx)
                append_entry(tx, '222', MAX_AMOUNT, 'test', 'test', 'test')
            self.assertEqual(self.post(amount=1).status_code, 400)
            self.assertEqual(len(self.db.select('star_shard')), 1)

    def test_concurrent_retries_pay_once(self):
        """Two workers retrying the same administrator request create one credit."""
        request_id = str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: grant(self.db, '111', '222', 50, request_id), range(2)))
        self.assertEqual(results[0]['id'], results[1]['id'])
        self.assertEqual(len(self.db.select('star_shard')), 1)
        with patch.object(self.service, '_request', return_value=self.live):
            self.assertEqual(self.post(requestId=request_id, amount=51).status_code, 400)

    def test_receipt_failure_rolls_back_credit(self):
        """Never retain minted shards if the audit receipt cannot be committed."""
        original = SQLSession.insert
        def insert(tx, table, values):
            """Fail the audit write after the ledger insert."""
            if table == 'star_shard_grant':
                raise RuntimeError('test')
            return original(tx, table, values)
        with patch.object(SQLSession, 'insert', insert):
            with self.assertRaises(RuntimeError):
                grant(self.db, '111', '222', 50, str(uuid4()))
        self.assertFalse(self.db.table_exists('star_shard'))

    def test_search_registered_recipients_includes_self(self):
        """Admin grants may target any registered member, including the administrator."""
        with patch.object(self.service, '_request', return_value=self.live):
            all_members = self.client.get('/api/admin/shards/members').json['members']
            self.assertEqual({row['userId'] for row in all_members}, {'111', '222'})
            result = self.client.get('/api/admin/shards/members?q=222').json['members']
            self.assertEqual([row['userId'] for row in result], ['222'])
