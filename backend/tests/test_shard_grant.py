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
        """Submit one protected system grant with configurable input.
        使用可覆寫的內容提交系統發放測試請求。

        Args:
            overrides: 覆寫預設測試請求內容的關鍵字參數。

        Returns:
            TestResponse: 系統發放的測試 HTTP 回應。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_shard_grant.py"
            對應測試或輔助流程：test_shard_grant.GrantTests。
        """
        return self.client.post('/api/admin/shards/grant', headers={'X-CSRF-Token': 'test'},
            json={'recipientId': '222', 'amount': 50, 'requestId': str(uuid4()), **overrides})

    def test_grant_is_system_income_with_auditable_administrator(self):
        """The server sets ledger type and description regardless of supplied fields.
        驗證系統發放類型與管理員稽核來源。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_shard_grant.py"
            對應測試或輔助流程：test_shard_grant.GrantTests.test_grant_is_system_income_with_auditable_administrator。
        """
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
        """Anonymous, stale role snapshots and forged requests cannot mint shards.
        驗證即時網頁管理員身份與 CSRF 發放限制。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_shard_grant.py"
            對應測試或輔助流程：test_shard_grant.GrantTests.test_only_live_web_admin_with_csrf_can_grant。
        """
        self.assertEqual(self.app.test_client().post('/api/admin/shards/grant').status_code, 401)
        self.assertEqual(self.client.post('/api/admin/shards/grant').status_code, 403)
        with patch.object(self.service, '_request', return_value={'user': {'id': '111'}, 'roles': [test_admin.MEMBER]}):
            self.assertEqual(self.post().status_code, 403)
            self.assertEqual(self.client.get('/api/admin/shards/members').status_code, 403)
        self.assertFalse(self.db.table_exists('star_shard'))

    def test_invalid_amount_recipient_and_overflow(self):
        """Reject nonpositive or unsafe amounts and unknown recipient IDs.
        驗證無效金額、接收者及餘額溢出。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_shard_grant.py"
            對應測試或輔助流程：test_shard_grant.GrantTests.test_invalid_amount_recipient_and_overflow。
        """
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
        """Two workers retrying the same administrator request create one credit.
        驗證並行重試僅派款一次。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_shard_grant.py"
            對應測試或輔助流程：test_shard_grant.GrantTests.test_concurrent_retries_pay_once。
        """
        request_id = str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: grant(self.db, '111', '222', 50, request_id), range(2)))
        self.assertEqual(results[0]['id'], results[1]['id'])
        self.assertEqual(len(self.db.select('star_shard')), 1)
        with patch.object(self.service, '_request', return_value=self.live):
            self.assertEqual(self.post(requestId=request_id, amount=51).status_code, 400)

    def test_receipt_failure_rolls_back_credit(self):
        """Never retain minted shards if the audit receipt cannot be committed.
        驗證憑證儲存失敗時回滾入帳。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_shard_grant.py"
            對應測試或輔助流程：test_shard_grant.GrantTests.test_receipt_failure_rolls_back_credit。
        """
        original = SQLSession.insert
        def insert(tx, table, values):
            """Fail the audit write after the ledger insert.
            在發放憑證新增時注入失敗，其餘新增沿用原方法。

            Args:
                tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。
                table: 資料表名稱。
                values: 欄位名稱與資料值的對照表。

            Returns:
                object: 被包裝操作的測試結果，供呼叫案例斷言。

            Exceptions:
                RuntimeError: 設定不一致或測試刻意注入的執行失敗。 若由下列處理流程捕捉，則依其轉換規則處理。

            Example:
                在 backend 目錄執行：python -m unittest discover -s tests -p "test_shard_grant.py"
                對應測試或輔助流程：test_shard_grant.GrantTests.test_receipt_failure_rolls_back_credit。
            """
            if table == 'star_shard_grant':
                raise RuntimeError('test')
            return original(tx, table, values)
        with patch.object(SQLSession, 'insert', insert):
            with self.assertRaises(RuntimeError):
                grant(self.db, '111', '222', 50, str(uuid4()))
        self.assertFalse(self.db.table_exists('star_shard'))

    def test_search_registered_recipients_includes_self(self):
        """Admin grants may target any registered member, including the administrator.
        驗證已登記接收者搜尋包含管理員本人。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_shard_grant.py"
            對應測試或輔助流程：test_shard_grant.GrantTests.test_search_registered_recipients_includes_self。
        """
        with patch.object(self.service, '_request', return_value=self.live):
            all_members = self.client.get('/api/admin/shards/members').json['members']
            self.assertEqual({row['userId'] for row in all_members}, {'111', '222'})
            result = self.client.get('/api/admin/shards/members?q=222').json['members']
            self.assertEqual([row['userId'] for row in result], ['222'])
