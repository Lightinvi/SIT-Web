"""Verify prediction authorization, accounting and atomic retries in isolated storage."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_admin
from app.models.member import record_login
from app.models.prediction import execute, ensure_schema, proportional
from app.models.star_shard import append_entry, balance, ShardError, MAX_AMOUNT


class PredictionTests(unittest.TestCase):
    """Exercise real transactions without Discord network access."""

    def setUp(self):
        """Reuse the authenticated isolated database fixture and fund three users.
        建立此測試案例所需的獨立環境與測試資料。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests。
        """
        test_admin.AdminTests.setUp(self)
        with self.db.transaction() as tx:
            record_login(tx, {'id': '333', 'name': '333', 'role_ids': [test_admin.MEMBER]}, 1)
            ensure_schema(tx)
            for user in ('111', '222', '333'):
                append_entry(tx, user, 100, 'system', str(uuid4()), 'Test funds')

    def command(self, action, data, market=None, user='111', role='web_admin', now=100, request=None):
        """Execute deterministic commands with unique receipts by default.
        以固定時間及指定身份執行預測操作，未指定時產生新操作 UUID。

        Args:
            action: 要執行的操作名稱。
            data: 操作所需的資料對照表。
            market: 已讀取的預測盤資料對照表。 預設為 None。
            user: 測試成員的 Discord 使用者 ID 字串。 預設為 '111'。
            role: 操作所使用的身份或權限名稱。 預設為 'web_admin'。
            now: Unix 秒數；支援 None 的函式會使用目前時間。 預設為 100。
            request: 測試操作識別碼，或 None 產生新值。 預設為 None。

        Returns:
            dict: 預測盤最新狀態。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests。
        """
        return execute(self.db, user, request or str(uuid4()), action, data,
                       market_id=market['id'] if market else None, role=role, now=now)

    def market(self, base=0):
        """Create a two-option market before its fixed betting deadline.
        建立具有固定截止及結算時間的測試預測盤。

        Args:
            base: 測試預測盤的基礎獎勵金額。 預設為 0。

        Returns:
            dict: 新建立的測試預測盤。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests。
        """
        return self.command('create', {'name': 'Test', 'options': ['A', 'B'],
                            'closesAt': 200, 'settlesAt': 300, 'baseReward': base})

    def stake(self, market, user, amount, option=0, **kwargs):
        """Place an integer stake against a selected option.
        對測試預測盤的指定選項下注。

        Args:
            market: 已讀取的預測盤資料對照表。
            user: 測試成員的 Discord 使用者 ID 字串。
            amount: 要扣除或發放的正整數碎片數量。
            option: 測試預測盤選項的索引。 預設為 0。
            kwargs: 轉交被呼叫方法的關鍵字參數。

        Returns:
            dict: 下注後的預測盤最新狀態。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests。
        """
        return self.command('bet', {'amount': amount, 'optionId': market['options'][option]['id']},
                            market, user=user, **kwargs)

    def funds(self, user):
        """Read the committed ledger balance.
        讀取測試成員已提交的帳本餘額。

        Args:
            user: 測試成員的 Discord 使用者 ID 字串。

        Returns:
            int: 已提交的碎片帳本餘額。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests。
        """
        with self.db.transaction() as tx:
            return balance(tx, user)

    def test_proportional_settlement_and_retry(self):
        """Pay the whole pool exactly once, aggregating repeated winning bets.
        驗證比例結算及重試不重複派款。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests.test_proportional_settlement_and_retry。
        """
        market = self.market(7)
        self.stake(market, '111', 1)
        self.stake(market, '111', 1)
        self.stake(market, '222', 1)
        self.stake(market, '333', 10, 1)
        receipt = str(uuid4())
        data = {'version': 1, 'winnerId': market['options'][0]['id']}
        result = self.command('settle', data, market, now=300, request=receipt)
        self.command('settle', data, market, now=301, request=receipt)
        self.assertEqual(result['status'], 'settled')
        self.assertEqual([self.funds(user) for user in ('111', '222', '333')], [111, 106, 90])
        self.assertEqual(len(self.db.select('prediction_payout')), 2)
        self.assertEqual(self.db.query('PRAGMA foreign_key_check'), [])

    def test_single_side_with_and_without_bonus(self):
        """Return principal when unopposed and share any sponsorship.
        驗證無對手盤時本金與基礎獎勵分配。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests.test_single_side_with_and_without_bonus。
        """
        for bonus in (0, 9):
            market = self.market(bonus)
            before = self.funds('222')
            self.stake(market, '222', 10)
            self.command('settle', {'version': 1, 'winnerId': market['options'][0]['id']}, market, now=300)
            self.assertEqual(self.funds('222'), before + bonus)

    def test_refund_no_winner_and_cancel(self):
        """Refund every user's stakes without minting unused sponsorship.
        驗證無人押中或取消時退還本金。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests.test_refund_no_winner_and_cancel。
        """
        for action in ('settle', 'cancel'):
            market = self.market(50)
            self.stake(market, '222', 10)
            self.stake(market, '222', 15)
            result = self.command(action, {'version': 1, 'winnerId': market['options'][1]['id']}, market, now=300)
            self.assertEqual(result['settlementMode'], 'refund')
            self.assertEqual(self.funds('222'), 100)

    def test_permissions_and_immutable_options(self):
        """Enforce sponsor privileges, monotonic rewards and immutable choices.
        驗證管理權限與建立後固定的預測選項。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests.test_permissions_and_immutable_options。
        """
        market = self.market(10)
        for data, error, role in [({'baseReward': 9}, ShardError, 'web_admin'),
                ({'baseReward': 11}, PermissionError, 'admin'),
                ({'options': ['C', 'D']}, ShardError, 'web_admin')]:
            with self.assertRaises(error):
                self.command('edit', {'version': 1, **data}, market, role=role)
        updated = self.command('edit', {'version': 1, 'name': 'Updated'}, market, role='admin')
        self.assertEqual(updated['baseReward'], 10)
        with self.assertRaises(ShardError):
            self.command('edit', {'version': 1, 'name': 'Stale'}, market)
        with self.assertRaises(PermissionError):
            self.command('cancel', {'version': 2}, market, role='member')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('UPDATE prediction_option SET label=?', ('Changed',))

    def test_deadlines_and_invalid_stakes(self):
        """Reject late bets, early settlement, cross-market choices and overspending.
        驗證押注及結算時間限制與無效押注。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests.test_deadlines_and_invalid_stakes。
        """
        market = self.market()
        other = self.market()
        for amount in (0, -1, 1.5, True, 101):
            with self.assertRaises(ShardError):
                self.stake(market, '222', amount)
        with self.assertRaises(ShardError):
            self.stake(market, '222', 1, now=200)
        with self.assertRaises(ShardError):
            self.command('bet', {'amount': 1, 'optionId': other['options'][0]['id']}, market)
        with self.assertRaises(ShardError):
            self.command('settle', {'version': 1, 'winnerId': market['options'][0]['id']}, market, now=299)
        with self.assertRaises(ShardError):
            self.command('edit', {'version': 1, 'closesAt': 250}, market, now=200)
        self.assertEqual(self.funds('222'), 100)

    def test_concurrent_retry_and_fingerprint(self):
        """Concurrent duplicate submissions debit once and cannot change their payload.
        驗證並行重試及操作內容指紋綁定。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests.test_concurrent_retry_and_fingerprint。
        """
        market = self.market()
        receipt = str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.stake(market, '222', 60, request=receipt), range(2)))
        self.assertEqual(results[0]['ownAmount'], 60)
        self.assertEqual(self.funds('222'), 40)
        self.assertEqual(len(self.db.select('prediction_bet')), 1)
        with self.assertRaises(ShardError):
            self.stake(market, '222', 1, request=receipt)

    def test_failed_payout_rolls_back_everything(self):
        """A recipient overflow cannot leave partial payouts or close the market.
        驗證派款失敗時回滾整次結算。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests.test_failed_payout_rolls_back_everything。
        """
        market = self.market(10)
        self.stake(market, '111', 1)
        self.stake(market, '222', 1)
        with self.db.transaction() as tx:
            append_entry(tx, '222', MAX_AMOUNT - 99, 'system', str(uuid4()), 'Fill balance')
        with self.assertRaises(ShardError):
            self.command('settle', {'version': 1, 'winnerId': market['options'][0]['id']}, market, now=300)
        self.assertEqual(self.funds('111'), 99)
        self.assertEqual(self.db.select('prediction_payout'), [])
        self.assertEqual(self.db.select('prediction_market')[0]['status'], 'active')

    def test_integer_distribution(self):
        """Largest remainders preserve the pool and deterministically break ties.
        驗證整數比例分配保留完整池額。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests.test_integer_distribution。
        """
        self.assertEqual(proportional({'222': 1, '111': 1}, 3), {'222': 1, '111': 2})
        for pool in range(6, 100):
            self.assertEqual(sum(proportional({'a': 1, 'b': 2, 'c': 3}, pool).values()), pool)

    def test_date_range_filters_before_pagination(self):
        """Include the start instant, exclude the next midnight, and paginate filtered rows.
        驗證日期篩選先於分頁且符合邊界。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests.test_date_range_filters_before_pagination。
        """
        for closes in (199, *([200] * 21), 299.999, 300):
            self.command('create', {'name': 'Range', 'options': ['A', 'B'],
                         'closesAt': closes, 'settlesAt': 400})
        first = self.client.get('/api/predictions?closesFrom=200&closesBefore=300').json
        second = self.client.get('/api/predictions?closesFrom=200&closesBefore=300&offset=20').json
        self.assertEqual(len(first['markets']), 20)
        self.assertEqual(first['nextOffset'], 20)
        self.assertEqual(len(second['markets']), 2)
        self.assertIsNone(second['nextOffset'])
        self.assertTrue(all(200 <= item['closesAt'] < 300 for item in first['markets'] + second['markets']))
        self.assertEqual(len({item['id'] for item in first['markets'] + second['markets']}), 22)
        self.assertEqual(self.client.get('/api/predictions?closesFrom=200&closesBefore=300&q=missing').json['markets'], [])

    def test_date_range_validation(self):
        """Reject incomplete, non-finite, reversed and unsupported ranges.
        驗證日期範圍輸入驗證。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests.test_date_range_validation。
        """
        for query in ('closesFrom=200', 'closesBefore=300', 'closesFrom=NaN&closesBefore=300',
                      'closesFrom=200&closesBefore=inf', 'closesFrom=300&closesBefore=200',
                      'closesFrom=200&closesBefore=200', 'closesFrom=&closesBefore=300',
                      'closesFrom=200&closesBefore=253402300800'):
            self.assertEqual(self.client.get('/api/predictions?' + query).status_code, 400, query)

    def test_api_auth_csrf_and_live_roles(self):
        """Require authentication and live administrator roles rather than cached claims.
        驗證預測 API 登入、CSRF 與即時身份組授權。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            在 backend 目錄執行：python -m unittest discover -s tests -p "test_prediction.py"
            對應測試或輔助流程：test_prediction.PredictionTests.test_api_auth_csrf_and_live_roles。
        """
        self.assertEqual(self.app.test_client().get('/api/predictions').status_code, 401)
        payload = {'requestId': str(uuid4()), 'name': 'API', 'options': ['A', 'B'],
                   'closesAt': 2000000000, 'settlesAt': 2000000001, 'baseReward': 1}
        self.assertEqual(self.client.post('/api/predictions', json=payload).status_code, 403)
        headers = {'X-CSRF-Token': 'test'}
        with patch.object(self.service, '_request', return_value={'user': {'id': '111'}, 'roles': [test_admin.MEMBER]}):
            self.assertEqual(self.client.post('/api/predictions', json=payload, headers=headers).status_code, 403)
        with patch.object(self.service, '_request', return_value=self.live):
            self.assertEqual(self.client.post('/api/predictions', json=payload, headers=headers).status_code, 200)
        response = self.client.get('/api/predictions')
        self.assertEqual(len(response.json['markets']), 1)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
