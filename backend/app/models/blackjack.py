"""Persistent American blackjack with one globally shared shoe and atomic shard accounting.

blackjack-api supplies cards, deck composition, ace scoring and pair evaluation.
The adapter owns American peek timing, split limits, exact integer payouts and
transactional state, which the upstream simulation loop does not implement.
"""
import json
import secrets
import time

from blackjack_api.card import Card
from blackjack_api.deck import Deck
from blackjack_api.hand import Hand

from app.models.record_ids import new_record_id
from app.models.star_shard import append_entry, balance, ensure_schema as ensure_ledger, ShardError


def ensure_schema(tx):
    """Create durable shoes, rounds and idempotency receipts in the caller's transaction."""
    ensure_ledger(tx)
    tx.execute('''CREATE TABLE IF NOT EXISTS blackjack_shoe (
        id TEXT PRIMARY KEY, cards TEXT NOT NULL, nextIndex INTEGER NOT NULL,
        createdAt REAL NOT NULL)''')
    tx.execute('''CREATE TABLE IF NOT EXISTS blackjack_round (
        id TEXT PRIMARY KEY, userId TEXT NOT NULL REFERENCES member(userId),
        state TEXT NOT NULL, status TEXT NOT NULL, createdAt REAL NOT NULL, updatedAt REAL NOT NULL)''')
    tx.execute("CREATE UNIQUE INDEX IF NOT EXISTS blackjack_active_user ON blackjack_round(userId) WHERE status != 'settled'")
    tx.execute('CREATE INDEX IF NOT EXISTS blackjack_user_latest ON blackjack_round(userId, createdAt DESC)')
    tx.execute('''CREATE TABLE IF NOT EXISTS blackjack_request (
        id TEXT PRIMARY KEY, userId TEXT NOT NULL REFERENCES member(userId),
        requestId TEXT NOT NULL, fingerprint TEXT NOT NULL, roundId TEXT NOT NULL REFERENCES blackjack_round(id),
        createdAt REAL NOT NULL, UNIQUE(userId, requestId))''')


def hand(cards):
    """Build the library's hand evaluator from persisted card identities."""
    result = Hand()
    for card in cards:
        result.push(Card(card['face']))
    return result


def natural(cards):
    """Only an original two-card 21 qualifies as a natural blackjack."""
    return len(cards) == 2 and hand(cards).count() == 21


def draw(tx):
    """Consume exactly one shared shoe position, refilling only after all 260 draws."""
    rows = tx.query('SELECT * FROM blackjack_shoe ORDER BY rowid DESC LIMIT 1')
    if not rows or rows[0]['nextIndex'] == 260:
        deck = Deck(5)
        cards = [str(deck.pop(0)) for _ in range(len(deck))]
        secrets.SystemRandom().shuffle(cards)
        shoe = {'id': new_record_id(), 'cards': json.dumps(cards), 'nextIndex': 0, 'createdAt': time.time()}
        tx.insert('blackjack_shoe', shoe)
    else:
        shoe = rows[0]
    position = shoe['nextIndex']
    card = {'id': f"{shoe['id']}:{position}", 'face': json.loads(shoe['cards'])[position]}
    tx.update('blackjack_shoe', {'nextIndex': position + 1}, {'id': shoe['id']})
    return card


def debit(tx, state, amount, description):
    """Debit a stake atomically, tracking total exposure for final net results."""
    append_entry(tx, state['userId'], -amount, 'blackjack', state['id'], description)
    state['staked'] += amount


def settle(tx, state, *, peek=False):
    """Play S17 dealer when necessary and credit gross returns exactly once."""
    if state['phase'] == 'settled':
        return
    dealer = state['dealer']
    hands = state['hands']
    if not peek and any(hand(item['cards']).count() <= 21 for item in hands):
        while hand(dealer).count() < 17:
            dealer.append(draw(tx))
    dealer_total = hand(dealer).count()
    dealer_natural = natural(dealer)
    payout = state['insurance'] * 3 if dealer_natural else 0
    state['insurancePayout'] = payout
    for item in hands:
        total = hand(item['cards']).count()
        blackjack = not item['split'] and natural(item['cards'])
        if total > 21:
            result, returned = 'bust', 0
        elif dealer_natural:
            result, returned = ('push', item['bet']) if blackjack else ('lose', 0)
        elif blackjack:
            result, returned = 'blackjack', item['bet'] * 5 // 2
        elif dealer_total > 21 or total > dealer_total:
            result, returned = 'win', item['bet'] * 2
        elif total == dealer_total:
            result, returned = 'push', item['bet']
        else:
            result, returned = 'lose', 0
        item.update(done=True, result=result, payout=returned)
        payout += returned
    if payout:
        append_entry(tx, state['userId'], payout, 'blackjack', state['id'], '21 點結算（含退回本金）')
    state.update(phase='settled', payout=payout, net=payout - state['staked'])


def after_peek(tx, state):
    """Resolve dealer naturals before player actions, and pay original player naturals."""
    if natural(state['dealer']) or natural(state['hands'][0]['cards']):
        settle(tx, state, peek=True)
    else:
        state['phase'] = 'player'


def advance(tx, state):
    """Advance through completed split hands or finish dealer play."""
    for index, item in enumerate(state['hands']):
        if hand(item['cards']).count() >= 21:
            item['done'] = True
        if not item['done']:
            state['activeHand'] = index
            return
    settle(tx, state)


def allowed(state, funds):
    """Return only legal actions that the current balance can fund."""
    if state['phase'] == 'insurance':
        return ['decline'] + (['insurance'] if funds >= state['baseBet'] // 2 else [])
    if state['phase'] != 'player':
        return []
    item = state['hands'][state['activeHand']]
    actions = ['hit', 'stand']
    if len(item['cards']) == 2 and funds >= item['bet']:
        actions.append('double')
        if len(state['hands']) < 4 and hand(item['cards']).can_split():
            actions.append('split')
    return actions


def public_state(tx, user_id, state=None):
    """Serialize only the requesting player's round, never the hole card or shoe order."""
    funds = balance(tx, user_id)
    if state is None:
        rows = tx.query('SELECT state FROM blackjack_round WHERE userId=? ORDER BY createdAt DESC, rowid DESC LIMIT 1', (user_id,))
        state = json.loads(rows[0]['state']) if rows else None
    if state is None:
        return {'balance': funds, 'round': None}
    view = json.loads(json.dumps(state))
    view.pop('userId', None)
    for item in view['hands']:
        item['total'] = hand(item['cards']).count()
    if state['phase'] != 'settled':
        view['dealer'] = [state['dealer'][0], None]
        view['dealerTotal'] = hand(state['dealer'][:1]).count()
    else:
        view['dealerTotal'] = hand(state['dealer']).count()
    view['actions'] = allowed(state, funds)
    return {'balance': funds, 'round': view}


def play(db, user_id, request_id, action, *, bet=None, round_id=None, version=None):
    """Serialize shared draws and ledger writes, rejecting stale or conflicting commands."""
    fingerprint = json.dumps([action, bet, round_id, version])
    with db.transaction(immediate=True) as tx:
        ensure_schema(tx)
        receipts = tx.select('blackjack_request', {'userId': user_id, 'requestId': request_id})
        if receipts:
            if receipts[0]['fingerprint'] != fingerprint:
                raise ShardError('此操作識別碼已用於其他操作，請重新確認牌局。')
            return public_state(tx, user_id)
        if action == 'start':
            if type(bet) is not int or bet < 2 or bet % 2 or bet > balance(tx, user_id):
                raise ShardError('下注須為至少 2 點的正偶數，且不可超過餘額。')
            if tx.query("SELECT id FROM blackjack_round WHERE userId=? AND status != 'settled'", (user_id,)):
                raise ShardError('請先完成目前的牌局。')
            state = {'id': new_record_id(), 'userId': user_id, 'version': 1, 'phase': 'player',
                     'baseBet': bet, 'staked': 0, 'insurance': 0, 'activeHand': 0,
                     'hands': [{'cards': [], 'bet': bet, 'done': False, 'split': False}], 'dealer': []}
            debit(tx, state, bet, '21 點下注')
            for _ in range(2):
                state['hands'][0]['cards'].append(draw(tx))
                state['dealer'].append(draw(tx))
            if state['dealer'][0]['face'].startswith('A'):
                state['phase'] = 'insurance'
            else:
                after_peek(tx, state)
            timestamp = time.time()
            tx.insert('blackjack_round', {'id': state['id'], 'userId': user_id, 'state': json.dumps(state),
                      'status': state['phase'], 'createdAt': timestamp, 'updatedAt': timestamp})
        else:
            rows = tx.select('blackjack_round', {'id': round_id, 'userId': user_id}) if isinstance(round_id, str) else []
            if not rows:
                raise ShardError('找不到牌局，請重新確認。')
            state = json.loads(rows[0]['state'])
            if type(version) is not int or version != state['version']:
                raise ShardError('牌局已更新，請重新確認後操作。')
            if action not in allowed(state, balance(tx, user_id)):
                raise ShardError('目前不能執行此操作，或星之碎片不足。')
            if action in ('insurance', 'decline'):
                if action == 'insurance':
                    state['insurance'] = state['baseBet'] // 2
                    debit(tx, state, state['insurance'], '21 點保險')
                after_peek(tx, state)
            else:
                item = state['hands'][state['activeHand']]
                if action == 'stand':
                    item['done'] = True
                elif action == 'hit':
                    item['cards'].append(draw(tx))
                elif action == 'double':
                    debit(tx, state, item['bet'], '21 點加倍下注')
                    item['bet'] *= 2
                    item['cards'].append(draw(tx))
                    item['done'] = True
                elif action == 'split':
                    debit(tx, state, item['bet'], '21 點分牌下注')
                    second = {'cards': [item['cards'].pop()], 'bet': item['bet'], 'done': False, 'split': True}
                    item['split'] = True
                    split_aces = item['cards'][0]['face'].startswith('A')
                    item['cards'].append(draw(tx))
                    second['cards'].append(draw(tx))
                    item['done'] = second['done'] = split_aces
                    state['hands'].insert(state['activeHand'] + 1, second)
                advance(tx, state)
            state['version'] += 1
            tx.update('blackjack_round', {'state': json.dumps(state), 'status': state['phase'], 'updatedAt': time.time()}, {'id': state['id']})
        tx.insert('blackjack_request', {'id': new_record_id(), 'userId': user_id, 'requestId': request_id,
                  'fingerprint': fingerprint, 'roundId': state['id'], 'createdAt': time.time()})
        return public_state(tx, user_id, state)
