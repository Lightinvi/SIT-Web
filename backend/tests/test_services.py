"""Verify application-owned objects, explicit transaction lifetimes and API delegation."""
import sqlite3
import unittest
from unittest.mock import patch

from app import create_app
from app.models.star_shard import ShardLedger, ShardTransferService, balance
from app.models.blackjack import BlackjackRound
import test_admin


class ServiceTests(unittest.TestCase):
    """Check the object contracts using isolated existing application fixtures.
    使用獨立應用程式資料驗證服務物件的隔離與交易契約。
    """

    def setUp(self):
        """Create an isolated application with registered member identities.
        建立獨立應用程式與已登記成員的測試資料。

        Args:
            None: 使用 unittest 提供的測試實例。

        Returns:
            None: 建立測試用戶端與資料庫。

        Example:
            執行：python -m unittest discover -s backend/tests -p test_services.py
        """
        test_admin.AdminTests.setUp(self)
        self.services = self.app.extensions['services']

    def test_applications_own_independent_service_dependencies(self):
        """Keep application service instances and database configuration isolated.
        確認不同應用程式持有獨立服務與資料庫相依項目。

        Args:
            None: 使用測試 fixture 的 app 與 db。

        Returns:
            None: 透過斷言驗證物件隔離。

        Example:
            執行：python -m unittest discover -s backend/tests -p test_services.py
        """
        other = create_app({'TESTING': True, 'SQL_DATABASE_PATH': self.temp.name + '/other.sqlite3'})
        self.assertIsInstance(self.services.shards, ShardTransferService)
        self.assertIs(self.services.shards.db, self.db)
        self.assertIsNot(self.services, other.extensions['services'])
        self.assertIsNot(self.services.shards, other.extensions['services'].shards)
        self.assertIsNot(self.services.shards.db, other.extensions['sql'])
        self.assertEqual(other.extensions['sql'].list_tables(), [])
        self.assertIs(self.services.oauth.config, self.app.config)

    def test_transaction_owned_ledger_agrees_with_compatibility_adapter(self):
        """Use the same transaction for class methods and legacy function adapters.
        驗證帳本物件與相容函式使用相同交易並取得相同結果。

        Args:
            None: 使用 fixture 中的成員 111。

        Returns:
            None: 驗證入帳與交易生命週期。

        Exceptions:
            sqlite3.ProgrammingError: 預期交易已關閉後的物件存取被拒絕。

        Example:
            執行：python -m unittest discover -s backend/tests -p test_services.py
        """
        with self.db.transaction(immediate=True) as tx:
            ledger = ShardLedger(tx)
            ledger.ensure_schema()
            record_id = ledger.append_entry('111', 10, 'system', 'test-source', 'test')
            self.assertEqual(ledger.balance('111'), balance(tx, '111'))
            self.assertEqual(len(record_id), 36)
        self.assertEqual(self.db.select('star_shard')[0]['afterBlance'], 10)
        with self.assertRaises(sqlite3.ProgrammingError):
            ledger.balance('111')

    def test_api_delegates_to_the_registered_transfer_object(self):
        """Resolve the registered service after authentication and CSRF validation.
        驗證 API 在登入及 CSRF 檢查後呼叫已註冊的轉讓服務物件。

        Args:
            None: 使用 fixture 的已登入測試用戶端。

        Returns:
            None: 驗證依賴注入與參數傳遞。

        Example:
            執行：python -m unittest discover -s backend/tests -p test_services.py
        """
        request_id = '00000000-0000-4000-8000-000000000001'
        with patch.object(self.services.shards, 'transfer', return_value={'balance': 5, 'recordId': 'test'}) as transfer:
            response = self.client.post('/api/star-shards/transfer', headers={'X-CSRF-Token': 'test'},
                json={'requestId': request_id, 'recipientId': '222', 'amount': 10})
        self.assertEqual(response.status_code, 200)
        transfer.assert_called_once_with('111', '222', 10, request_id)

    def test_round_encapsulates_shared_state_and_ledger(self):
        """Debit through a round object and roll back its ledger transaction on failure.
        驗證牌局物件更新共同狀態，且失敗交易不留下帳本異動。

        Args:
            None: 使用 fixture 的資料庫。

        Returns:
            None: 驗證牌局狀態與交易資料一致性。

        Exceptions:
            RuntimeError: 測試刻意拋出以驗證交易回滾。

        Example:
            執行：python -m unittest discover -s backend/tests -p test_services.py
        """
        with self.db.transaction(immediate=True) as tx:
            ledger = ShardLedger(tx)
            ledger.ensure_schema()
            ledger.append_entry('111', 100, 'system', 'test', 'test')
        state = {'id': 'test-round', 'userId': '111', 'staked': 0}
        with self.assertRaises(RuntimeError):
            with self.db.transaction(immediate=True) as tx:
                round_object = BlackjackRound(tx, state)
                round_object.debit(20, 'test bet')
                self.assertEqual(state['staked'], 20)
                self.assertIs(round_object.state, state)
                raise RuntimeError('rollback')
        self.assertEqual(len(self.db.select('star_shard')), 1)
