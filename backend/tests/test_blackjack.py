"""Verify American rules, hidden information, shared shoes, and atomic shard settlement."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_admin
from app.models.blackjack import draw, ensure_schema, play
from app.models.star_shard import append_entry, balance, ShardError


class BlackjackTests(unittest.TestCase):
    """Exercise real SQLite transactions and HTTP sessions with deterministic shoes."""

    def setUp(self):
        """Create two funded players without making network requests."""
        test_admin.AdminTests.setUp(self)
        with self.db.transaction(immediate=True) as tx:
            ensure_schema(tx)
            for user_id in ('111', '222'):
                append_entry(tx, user_id, 1000, 'test', 'seed', 'test')

    def shoe(self, cards):
        """Install a controlled shoe in this test's private database."""
        self.db.insert('blackjack_shoe', {'id': str(uuid4()), 'cards': json.dumps(cards + ['2C'] * (260 - len(cards))), 'nextIndex': 0, 'createdAt': time.time()})

    def command(self, action, **overrides):
        """Submit the latest own round version unless the test overrides it."""
        current = self.client.get('/api/blackjack').json['round']
        payload = {'action': action, 'requestId': str(uuid4())}
        if action == 'start':
            payload['bet'] = 20
        elif current:
            payload.update(roundId=current['id'], version=current['version'])
        return self.client.post('/api/blackjack', json={**payload, **overrides}, headers={'X-CSRF-Token': 'test'})

    def test_natural_payout_and_hidden_information(self):
        """Natural pays 3:2; active responses never expose the hole card or shoe."""
        self.shoe(['AC', '9C', 'KH', '8D'])
        result = self.command('start').json
        self.assertEqual(result['balance'], 1030)
        self.assertEqual(result['round']['hands'][0]['result'], 'blackjack')
        self.assertEqual(result['round']['payout'], 50)
        self.shoe(['10C', '9C', '8H', '7D'])
        state = self.command('start').json
        self.assertIsNone(state['round']['dealer'][1])
        self.assertNotIn('7D', json.dumps(state))
        self.assertNotIn('shoe', state)

    def test_insurance_blackjack_and_decline(self):
        """Insurance returns three times its cost, independent of main-hand losses."""
        self.shoe(['10C', 'AC', '9H', 'KD'])
        start = self.command('start').json
        self.assertEqual(start['round']['phase'], 'insurance')
        self.assertEqual(start['balance'], 980)
        self.assertIsNone(start['round']['dealer'][1])
        result = self.command('insurance').json
        self.assertEqual(result['balance'], 1000)
        self.assertEqual(result['round']['insurancePayout'], 30)
        self.assertEqual(result['round']['net'], 0)
        self.shoe(['10C', 'AC', '9H', 'KD'])
        self.command('start')
        self.assertEqual(self.command('decline').json['balance'], 980)

    def test_soft17_and_losing_insurance(self):
        """Dealer stands on soft 17 and losing insurance is not refunded."""
        self.shoe(['10C', 'AC', '9H', '6D', 'KC'])
        self.command('start')
        self.command('insurance')
        result = self.command('stand').json
        self.assertEqual(result['balance'], 1010)
        self.assertEqual(result['round']['dealerTotal'], 17)
        self.assertEqual(len(result['round']['dealer']), 2)

    def test_ten_up_peek_and_both_naturals(self):
        """Ten-up dealer blackjack resolves before any extra player wagers."""
        self.shoe(['8C', 'KC', '8H', 'AD'])
        result = self.command('start').json
        self.assertEqual(result['round']['phase'], 'settled')
        self.assertEqual(result['balance'], 980)
        self.assertEqual(result['round']['actions'], [])
        self.shoe(['AC', 'KC', 'KH', 'AD'])
        result = self.command('start').json
        self.assertEqual(result['balance'], 980)
        self.assertEqual(result['round']['hands'][0]['result'], 'push')

    def test_double_one_card_and_dealer_bust(self):
        """Doubling debits the extra stake and stops after exactly one card."""
        self.shoe(['5C', '6C', '6H', 'KD', '10H', 'QC'])
        self.command('start')
        result = self.command('double').json
        self.assertEqual(result['balance'], 1040)
        self.assertEqual(len(result['round']['hands'][0]['cards']), 3)
        self.assertEqual(result['round']['staked'], 40)
        self.assertEqual(result['round']['payout'], 80)

    def test_split_aces_stop_and_never_pay_natural(self):
        """Split aces receive one card each; their 21 pays ordinary 1:1."""
        self.shoe(['AC', '9C', 'AH', '8D', 'KC', 'AD'])
        self.command('start')
        result = self.command('split').json
        self.assertEqual(result['round']['phase'], 'settled')
        self.assertEqual([len(item['cards']) for item in result['round']['hands']], [2, 2])
        self.assertEqual(result['round']['hands'][0]['payout'], 40)
        self.assertEqual(result['round']['hands'][1]['result'], 'lose')
        self.assertEqual(result['balance'], 1000)

    def test_split_limit_and_double_after_split(self):
        """Re-splitting is bounded at four hands, and split hands may double."""
        self.shoe(['8C', '9C', '8H', '8D', '8C', '8D', '8H', '8S', '8C', '8H', '2S'])
        self.command('start')
        for _ in range(3):
            self.assertEqual(self.command('split').status_code, 200)
        current = self.client.get('/api/blackjack').json['round']
        self.assertEqual(len(current['hands']), 4)
        self.assertNotIn('split', current['actions'])
        self.assertIn('double', current['actions'])
        result = self.command('double').json
        self.assertEqual(result['round']['hands'][0]['bet'], 40)
        self.assertEqual(result['round']['activeHand'], 1)

    def test_player_bust_loses_without_drawing_dealer(self):
        """A busted player cannot win even if dealer might bust later."""
        self.shoe(['KC', '6C', '9H', 'KD', 'QC'])
        self.command('start')
        result = self.command('hit').json
        self.assertEqual(result['balance'], 980)
        self.assertEqual(len(result['round']['dealer']), 2)
        self.assertEqual(result['round']['hands'][0]['result'], 'bust')

    def test_balance_validation_csrf_and_ownership(self):
        """Reject invalid stakes, anonymous requests, CSRF failures, and another round."""
        self.assertEqual(self.app.test_client().get('/api/blackjack').status_code, 401)
        self.assertEqual(self.client.post('/api/blackjack', json={}).status_code, 403)
        for amount in (0, -2, 3, 1002, True, 2.5, '20'):
            self.assertEqual(self.command('start', bet=amount).status_code, 400)
        self.shoe(['8C', '6C', '8H', 'KD'])
        self.command('start', bet=1000)
        current = self.client.get('/api/blackjack').json
        self.assertEqual(current['balance'], 0)
        self.assertEqual(current['round']['actions'], ['hit', 'stand'])
        self.assertEqual(self.command('double').status_code, 400)
        with self.assertRaises(ShardError):
            play(self.db, '222', str(uuid4()), 'stand', round_id=current['round']['id'], version=1)

    def test_retries_and_stale_commands_do_not_draw_or_charge_twice(self):
        """Same-ID concurrent starts commit once; stale commands never consume cards."""
        self.shoe(['5C', '9C', '6H', '8D', '2C', '3C'])
        request_id = str(uuid4())
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: play(self.db, '111', request_id, 'start', bet=20), range(2)))
        self.assertTrue(all(result['balance'] == 980 for result in results))
        state = results[0]['round']
        action_id = str(uuid4())
        play(self.db, '111', action_id, 'hit', round_id=state['id'], version=1)
        play(self.db, '111', action_id, 'hit', round_id=state['id'], version=1)
        self.assertEqual(self.db.select('blackjack_shoe')[0]['nextIndex'], 5)
        with self.assertRaises(ShardError):
            play(self.db, '111', str(uuid4()), 'hit', round_id=state['id'], version=1)
        with self.assertRaises(ShardError):
            play(self.db, '111', request_id, 'start', bet=40)

    def test_shared_shoe_has_260_unique_positions_and_five_each_face(self):
        """All five decks are consumed before the next shared shoe is created."""
        with self.db.transaction(immediate=True) as tx:
            cards = [draw(tx) for _ in range(260)]
            self.assertEqual(len(tx.select('blackjack_shoe')), 1)
            next_card = draw(tx)
            self.assertEqual(len(tx.select('blackjack_shoe')), 2)
        self.assertEqual(len({card['id'] for card in cards}), 260)
        self.assertEqual(set(Counter(card['face'] for card in cards).values()), {5})
        self.assertEqual(len(Counter(card['face'] for card in cards)), 52)
        self.assertNotIn(next_card['id'], {card['id'] for card in cards})

    def test_two_players_share_positions_and_failure_rolls_back(self):
        """Concurrent players consume one global sequence and invalid actions leave it intact."""
        self.shoe(['2C'] * 20)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda user: play(self.db, user, str(uuid4()), 'start', bet=20), ['111', '222']))
        self.assertEqual(self.db.select('blackjack_shoe')[0]['nextIndex'], 8)
        player_cards = [card['id'] for result in results for card in result['round']['hands'][0]['cards']]
        self.assertEqual(len(set(player_cards)), 4)
        before = self.db.select('star_shard')
        with self.assertRaises(ShardError):
            play(self.db, '111', str(uuid4()), 'start', bet=20)
        self.assertEqual(self.db.select('star_shard'), before)

    def test_settlement_retry_and_failed_draw_are_atomic(self):
        """A failed draw rolls back its debit and a replayed settlement never pays twice."""
        self.shoe(['10C', '9C', '9H', '8D'])
        current = self.command('start').json['round']
        before = self.db.select('star_shard')
        with patch('app.models.blackjack.draw', side_effect=RuntimeError('test draw failure')):
            with self.assertRaises(RuntimeError):
                play(self.db, '111', str(uuid4()), 'double', round_id=current['id'], version=1)
        self.assertEqual(self.db.select('star_shard'), before)
        self.assertEqual(self.db.select('blackjack_shoe')[0]['nextIndex'], 4)
        request_id = str(uuid4())
        for _ in range(3):
            result = play(self.db, '111', request_id, 'stand', round_id=current['id'], version=1)
            self.assertEqual(result['balance'], 1020)
        payouts = [row for row in self.db.select('star_shard') if row['transactionType'] == 'blackjack' and row['amount'] > 0]
        self.assertEqual(len(payouts), 1)
        self.assertEqual(payouts[0]['transactionSource'], current['id'])
