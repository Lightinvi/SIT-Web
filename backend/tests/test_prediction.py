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
        """Reuse the authenticated isolated database fixture and fund three users."""
        test_admin.AdminTests.setUp(self)
        with self.db.transaction() as tx:
            record_login(tx, {'id': '333', 'name': '333', 'role_ids': [test_admin.MEMBER]}, 1)
            ensure_schema(tx)
            for user in ('111', '222', '333'):
                append_entry(tx, user, 100, 'system', str(uuid4()), 'Test funds')

    def command(self, action, data, market=None, user='111', role='web_admin', now=100, request=None):
        """Execute deterministic commands with unique receipts by default."""
        return execute(self.db, user, request or str(uuid4()), action, data,
                       market_id=market['id'] if market else None, role=role, now=now)

    def market(self, base=0):
        """Create a two-option market before its fixed betting deadline."""
        return self.command('create', {'name': 'Test', 'options': ['A', 'B'],
                            'closesAt': 200, 'settlesAt': 300, 'baseReward': base})

    def stake(self, market, user, amount, option=0, **kwargs):
        """Place an integer stake against a selected option."""
        return self.command('bet', {'amount': amount, 'optionId': market['options'][option]['id']},
                            market, user=user, **kwargs)

    def funds(self, user):
        """Read the committed ledger balance."""
        with self.db.transaction() as tx:
            return balance(tx, user)

    def test_proportional_settlement_and_retry(self):
        """Pay the whole pool exactly once, aggregating repeated winning bets."""
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
        """Return principal when unopposed and share any sponsorship."""
        for bonus in (0, 9):
            market = self.market(bonus)
            before = self.funds('222')
            self.stake(market, '222', 10)
            self.command('settle', {'version': 1, 'winnerId': market['options'][0]['id']}, market, now=300)
            self.assertEqual(self.funds('222'), before + bonus)

    def test_refund_no_winner_and_cancel(self):
        """Refund every user's stakes without minting unused sponsorship."""
        for action in ('settle', 'cancel'):
            market = self.market(50)
            self.stake(market, '222', 10)
            self.stake(market, '222', 15)
            result = self.command(action, {'version': 1, 'winnerId': market['options'][1]['id']}, market, now=300)
            self.assertEqual(result['settlementMode'], 'refund')
            self.assertEqual(self.funds('222'), 100)

    def test_permissions_and_immutable_options(self):
        """Enforce sponsor privileges, monotonic rewards and immutable choices."""
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
        """Reject late bets, early settlement, cross-market choices and overspending."""
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
        """Concurrent duplicate submissions debit once and cannot change their payload."""
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
        """A recipient overflow cannot leave partial payouts or close the market."""
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
        """Largest remainders preserve the pool and deterministically break ties."""
        self.assertEqual(proportional({'222': 1, '111': 1}, 3), {'222': 1, '111': 2})
        for pool in range(6, 100):
            self.assertEqual(sum(proportional({'a': 1, 'b': 2, 'c': 3}, pool).values()), pool)

    def test_date_range_filters_before_pagination(self):
        """Include the start instant, exclude the next midnight, and paginate filtered rows."""
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
        """Reject incomplete, non-finite, reversed and unsupported ranges."""
        for query in ('closesFrom=200', 'closesBefore=300', 'closesFrom=NaN&closesBefore=300',
                      'closesFrom=200&closesBefore=inf', 'closesFrom=300&closesBefore=200',
                      'closesFrom=200&closesBefore=200', 'closesFrom=&closesBefore=300',
                      'closesFrom=200&closesBefore=253402300800'):
            self.assertEqual(self.client.get('/api/predictions?' + query).status_code, 400, query)

    def test_api_auth_csrf_and_live_roles(self):
        """Require authentication and live administrator roles rather than cached claims."""
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
