"""Verify odds, system-local midnight, DST boundaries, and atomic daily payouts."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import time
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from app import create_app
from app.api.auth import database, digest
from app.models.daily_spinner import PRIZES, choose_prize, day_window, ensure_schema, spin
from app.models.member import record_login
from app.models.star_shard import MAX_AMOUNT, ShardError, append_entry, balance
from app.sql import SQLSession


class DailySpinnerTests(unittest.TestCase):
    """Use temporary SQLite storage and real login cookies without external services."""

    def setUp(self):
        """Prepare two members and an authenticated test browser."""
        original_timezone = os.environ.get('TZ')
        def restore_timezone():
            """Restore the process timezone after each isolated test."""
            if original_timezone is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = original_timezone
            time.tzset()
        self.addCleanup(restore_timezone)
        os.environ['TZ'] = 'UTC'
        time.tzset()
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'spinner-test',
            'SQL_DATABASE_PATH': str(Path(self.temp.name) / 'test.sqlite3')})
        self.db = self.app.extensions['sql']
        with self.app.app_context():
            database()
        with self.db.transaction(immediate=True) as tx:
            record_login(tx, {'id': '111', 'username': 'alice'}, 1)
            record_login(tx, {'id': '222', 'username': 'bob'}, 1)
            ensure_schema(tx)
        self.db.insert('login_sessions', {'id': digest('spinner'), 'user': json.dumps({'id': '111'}), 'expires': 4000000000})
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['login_id'] = 'spinner'
            session['csrf'] = 'token'
        self.before_midnight = datetime(2026, 9, 29, 23, 59, 59, tzinfo=timezone.utc).timestamp()

    def draw(self, **extra):
        """Request a draw with valid CSRF and optional untrusted JSON fields."""
        return self.client.post('/api/daily-spinner/spin', headers={'X-CSRF-Token': 'token'},
            json={'requestId': str(uuid4()), **extra})

    def test_exact_published_probability_mapping(self):
        """Enumerate all random outcomes to prove each multiplier's exact probability."""
        outcomes = Counter()
        for roll in range(100):
            with patch('app.models.daily_spinner.secrets.randbelow', return_value=roll) as random:
                outcomes[choose_prize()['multiplier']] += 1
                random.assert_called_once_with(100)
        self.assertEqual(outcomes, {0.5: 8, 1: 65, 2: 12, 2.5: 11, 5: 4})
        self.assertEqual([prize['reward'] for prize in PRIZES], [5, 10, 20, 25, 50])

    def test_public_odds_and_authenticated_status_are_read_only(self):
        """Publish odds anonymously without awarding shards or exposing other users."""
        public = self.app.test_client().get('/api/daily-spinner')
        self.assertFalse(public.json['authenticated'])
        self.assertFalse(public.json['canSpin'])
        self.assertNotIn('csrfToken', public.json)
        self.assertEqual(public.json['prizes'], list(PRIZES))
        status = self.client.get('/api/daily-spinner?userId=222')
        self.assertEqual(status.headers['Cache-Control'], 'no-store')
        self.assertTrue(status.json['canSpin'])
        self.assertEqual(status.json['userId'], '111')
        self.assertEqual(self.db.select('daily_spinner'), [])
        self.assertEqual(self.db.select('star_shard'), [])

    def test_draw_credits_ledger_with_receipt_source(self):
        """Ignore forged reward/user fields and use the committed daily receipt as source."""
        with patch('app.models.daily_spinner.secrets.randbelow', return_value=99):
            response = self.draw(userId='222', reward=99999, multiplier=100)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['awarded'])
        result = response.json['result']
        self.assertEqual((result['userId'], result['reward'], result['multiplier']), ('111', 50, 5))
        record = self.db.select('star_shard')[0]
        self.assertEqual((record['transactionType'], record['transactionSource']), ('daily_spinner', str(result['id'])))
        self.assertEqual((record['amount'], record['beforeBlance'], record['afterBlance']), (50, 0, 50))
        self.assertEqual(balance(self.db, '222'), 0)

    def test_duplicate_requests_reuse_daily_result(self):
        """Different request IDs on the same day still award exactly once."""
        first = self.draw().json
        second = self.draw().json
        self.assertEqual(first['result'], second['result'])
        self.assertFalse(second['awarded'])
        self.assertFalse(self.client.get('/api/daily-spinner').json['canSpin'])
        self.assertEqual(len(self.db.select('star_shard')), 1)

    def test_system_midnight_and_cross_day_retries(self):
        """Refresh at host midnight and never turn a prior-day retry into a second draw."""
        day, reset = day_window(self.before_midnight)
        self.assertEqual(day, '2026-09-29')
        self.assertEqual(reset, self.before_midnight + 1)
        request_id = str(uuid4())
        first = spin(self.db, '111', request_id, now=self.before_midnight)
        retry = spin(self.db, '111', request_id, now=reset)
        self.assertEqual(retry['result']['id'], first['result']['id'])
        self.assertTrue(retry['canSpin'])
        self.assertIsNone(retry['todaySpin'])
        second = spin(self.db, '111', str(uuid4()), now=reset)
        self.assertEqual(second['result']['spinDate'], '2026-09-30')
        self.assertTrue(second['awarded'])
        self.assertEqual(len(self.db.select('star_shard')), 2)

    def test_host_timezone_changes_calendar_boundary(self):
        """Respect UTC, Taiwan, and Oregon host settings instead of a fixed offset."""
        instant = datetime(2026, 9, 29, 20, tzinfo=timezone.utc).timestamp()
        cases = [('UTC', '2026-09-29', '2026-09-30T00:00:00+00:00'),
                 ('Asia/Taipei', '2026-09-30', '2026-09-30T16:00:00+00:00'),
                 ('America/Los_Angeles', '2026-09-29', '2026-09-30T07:00:00+00:00')]
        for zone, expected_day, expected_reset in cases:
            with self.subTest(zone=zone):
                os.environ['TZ'] = zone
                time.tzset()
                day, reset = day_window(instant)
                self.assertEqual(day, expected_day)
                self.assertEqual(reset, datetime.fromisoformat(expected_reset).timestamp())

    def test_oregon_dst_days_are_23_or_25_hours(self):
        """Resolve midnight using host DST rules instead of adding 86400 seconds."""
        os.environ['TZ'] = 'America/Los_Angeles'
        time.tzset()
        for start, hours in [('2026-03-08T08:00:00+00:00', 23), ('2026-11-01T07:00:00+00:00', 25)]:
            timestamp = datetime.fromisoformat(start).timestamp()
            _, reset = day_window(timestamp)
            self.assertEqual(reset - timestamp, hours * 3600)

    def test_parallel_draws_award_once(self):
        """Serialize simultaneous tabs so only one random result and credit is written."""
        with ThreadPoolExecutor(max_workers=6) as executor:
            results = list(executor.map(lambda _: spin(self.db, '111', str(uuid4()), now=self.before_midnight), range(6)))
        self.assertEqual(sum(result['awarded'] for result in results), 1)
        self.assertEqual(len({result['result']['id'] for result in results}), 1)
        self.assertEqual(len(self.db.select('daily_spinner')), 1)
        self.assertEqual(len(self.db.select('star_shard')), 1)

    def test_failed_credit_rolls_back_daily_eligibility(self):
        """A failed ledger insert cannot consume the user's daily turn."""
        insert = SQLSession.insert
        def fail_credit(tx, table, values):
            """Simulate disk failure only while appending the reward entry."""
            if table == 'star_shard':
                raise sqlite3.OperationalError('disk failure')
            return insert(tx, table, values)
        with patch.object(SQLSession, 'insert', fail_credit), self.assertLogs(self.app.logger, level='ERROR'):
            self.assertEqual(self.draw().status_code, 503)
        self.assertEqual(self.db.select('daily_spinner'), [])
        self.assertEqual(self.db.select('star_shard'), [])
        self.assertTrue(self.client.get('/api/daily-spinner').json['canSpin'])
        self.assertEqual(self.draw().status_code, 200)

    def test_overflow_rolls_back_spin(self):
        """Do not consume a turn when the ledger rejects an overflowing balance."""
        with self.db.transaction(immediate=True) as tx:
            append_entry(tx, '111', MAX_AMOUNT, 'test', 'test', 'max balance')
        with self.assertRaises(ShardError):
            spin(self.db, '111', str(uuid4()))
        self.assertEqual(self.db.select('daily_spinner'), [])

    def test_auth_csrf_and_invalid_request_ids(self):
        """Reject unsigned, expired, or malformed reward claims before any write."""
        self.assertEqual(self.app.test_client().post('/api/daily-spinner/spin', json={}).status_code, 401)
        self.assertEqual(self.client.post('/api/daily-spinner/spin', json={}).status_code, 403)
        for request_id in ('bad', None, 123, []):
            self.assertEqual(self.draw(requestId=request_id).status_code, 400)
        self.db.update('login_sessions', {'expires': 0}, {'id': digest('spinner')})
        self.assertEqual(self.draw().status_code, 401)
        self.assertEqual(self.db.select('daily_spinner'), [])

    def test_member_receipts_are_independent_and_immutable(self):
        """Different members may draw daily while existing results cannot be modified."""
        request_id = str(uuid4())
        first = spin(self.db, '111', request_id, now=self.before_midnight)
        second = spin(self.db, '222', request_id, now=self.before_midnight)
        self.assertNotEqual(first['result']['id'], second['result']['id'])
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.delete('daily_spinner', {'id': first['result']['id']})
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.update('daily_spinner', {'reward': 100}, {'id': first['result']['id']})
