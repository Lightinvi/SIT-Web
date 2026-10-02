"""Atomic pooled predictions, immutable options, integer payouts and audited commands."""
import json
import math
import time

from app.models.record_ids import new_record_id
from app.models.star_shard import MAX_AMOUNT, ShardError, append_entry, balance, ensure_schema as ensure_ledger


def ensure_schema(tx):
    """Create markets, immutable choices, stakes, payouts and idempotent audit events."""
    ensure_ledger(tx)
    tx.execute('''CREATE TABLE IF NOT EXISTS prediction_market (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
        closesAt REAL NOT NULL, settlesAt REAL NOT NULL, baseReward INTEGER NOT NULL CHECK(baseReward >= 0),
        status TEXT NOT NULL, winnerId TEXT, settlementMode TEXT,
        createdBy TEXT NOT NULL REFERENCES member(userId), settledBy TEXT REFERENCES member(userId),
        version INTEGER NOT NULL, createdAt REAL NOT NULL, updatedAt REAL NOT NULL, settledAt REAL)''')
    tx.execute('''CREATE TABLE IF NOT EXISTS prediction_option (
        id TEXT PRIMARY KEY, marketId TEXT NOT NULL REFERENCES prediction_market(id),
        label TEXT NOT NULL, position INTEGER NOT NULL, UNIQUE(marketId, position))''')
    tx.execute('''CREATE TABLE IF NOT EXISTS prediction_bet (
        id TEXT PRIMARY KEY, marketId TEXT NOT NULL REFERENCES prediction_market(id),
        optionId TEXT NOT NULL REFERENCES prediction_option(id), userId TEXT NOT NULL REFERENCES member(userId),
        amount INTEGER NOT NULL CHECK(typeof(amount) = 'integer' AND amount > 0),
        recordId TEXT NOT NULL REFERENCES star_shard(id), createdAt REAL NOT NULL)''')
    tx.execute('''CREATE TABLE IF NOT EXISTS prediction_payout (
        id TEXT PRIMARY KEY, marketId TEXT NOT NULL REFERENCES prediction_market(id),
        userId TEXT NOT NULL REFERENCES member(userId), amount INTEGER NOT NULL CHECK(amount > 0),
        kind TEXT NOT NULL, recordId TEXT NOT NULL REFERENCES star_shard(id), createdAt REAL NOT NULL,
        UNIQUE(marketId, userId))''')
    tx.execute('''CREATE TABLE IF NOT EXISTS prediction_event (
        id TEXT PRIMARY KEY, marketId TEXT NOT NULL REFERENCES prediction_market(id),
        userId TEXT NOT NULL REFERENCES member(userId), requestId TEXT NOT NULL,
        action TEXT NOT NULL, fingerprint TEXT NOT NULL, detail TEXT NOT NULL, createdAt REAL NOT NULL,
        UNIQUE(userId, requestId))''')
    tx.execute('CREATE INDEX IF NOT EXISTS prediction_bets_market ON prediction_bet(marketId, optionId, userId)')
    tx.execute('CREATE INDEX IF NOT EXISTS prediction_markets_created ON prediction_market(createdAt DESC)')
    for table in ('prediction_option', 'prediction_bet', 'prediction_payout', 'prediction_event'):
        for operation in ('UPDATE', 'DELETE'):
            tx.execute(f'''CREATE TRIGGER IF NOT EXISTS {table}_no_{operation.lower()}
                BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'Prediction records are immutable'); END''')


def get_market(tx, market_id):
    """Read one market or raise a public validation error."""
    rows = tx.select('prediction_market', {'id': market_id}) if isinstance(market_id, str) else []
    if not rows:
        raise ShardError('找不到預測盤。')
    return rows[0]


def market_view(tx, market, user_id, now):
    """Calculate current gross odds and own stakes, without exposing other bettors."""
    options = tx.query('''SELECT o.id, o.label, coalesce(sum(b.amount), 0) AS total,
        coalesce(sum(CASE WHEN b.userId=? THEN b.amount ELSE 0 END), 0) AS ownAmount
        FROM prediction_option o LEFT JOIN prediction_bet b ON b.optionId=o.id
        WHERE o.marketId=? GROUP BY o.id ORDER BY o.position''', (user_id, market['id']))
    staked = sum(option['total'] for option in options)
    pool = staked + market['baseReward']
    for option in options:
        option['odds'] = pool / option['total'] if option['total'] else None
    payouts = tx.select('prediction_payout', {'marketId': market['id'], 'userId': user_id})
    phase = market['status']
    if phase == 'active':
        phase = 'open' if now < market['closesAt'] else 'closed' if now < market['settlesAt'] else 'awaiting_result'
    return {**market, 'phase': phase, 'options': options, 'totalStaked': staked, 'pool': pool,
            'ownAmount': sum(option['ownAmount'] for option in options),
            'ownPayout': payouts[0]['amount'] if payouts else 0}


def text(value, label, limit, *, empty=False):
    """Validate bounded, human-readable metadata without interpreting markup."""
    if not isinstance(value, str) or len(value.strip()) > limit or (not empty and not value.strip()):
        raise ShardError(f'{label}格式不正確（最多 {limit} 字）。')
    return value.strip()


def timestamp(value):
    """Accept finite Unix seconds representable by the browser date controls."""
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 253402300800:
        raise ShardError('請提供有效的截止與結算時間。')
    return value


def integer(value, *, zero=False):
    """Require integer shard amounts within the ledger's safe numeric range."""
    if type(value) is not int or not (0 if zero else 1) <= value <= MAX_AMOUNT:
        raise ShardError('星之碎片數量必須為有效整數。')
    return value


def proportional(weights, pool):
    """Allocate the exact integer pool using largest remainders aggregated per user."""
    total = sum(weights.values())
    allocations = {user: pool * amount // total for user, amount in weights.items()}
    remaining = pool - sum(allocations.values())
    order = sorted(weights, key=lambda user: (-(pool * weights[user] % total), user))
    for user in order[:remaining]:
        allocations[user] += 1
    return allocations


def execute(db, user_id, request_id, action, data, *, market_id=None, role=None, now=None):
    """Commit one intent with all ledger effects, rejecting stale administrative edits."""
    if action != 'bet' and role not in ('admin', 'web_admin'):
        raise PermissionError('僅限管理員以上操作。')
    fingerprint = json.dumps([action, market_id, data], sort_keys=True, ensure_ascii=False)
    with db.transaction(immediate=True) as tx:
        ensure_schema(tx)
        now = time.time() if now is None else now
        previous = tx.select('prediction_event', {'userId': user_id, 'requestId': request_id})
        if previous:
            if previous[0]['fingerprint'] != fingerprint:
                raise ShardError('操作識別碼已使用，請重新確認。')
            return market_view(tx, get_market(tx, previous[0]['marketId']), user_id, now)
        detail = {}
        if action == 'create':
            name = text(data.get('name'), '名稱', 120)
            description = text(data.get('description', ''), '說明', 2000, empty=True)
            closes = timestamp(data.get('closesAt'))
            settles = timestamp(data.get('settlesAt'))
            if closes <= now or settles < closes:
                raise ShardError('最後押注時間須晚於現在，結算時間不得早於最後押注時間。')
            base = integer(data.get('baseReward', 0), zero=True)
            if base and role != 'web_admin':
                raise PermissionError('只有網頁管理員可添加基礎獎勵。')
            labels = data.get('options')
            if not isinstance(labels, list) or not 2 <= len(labels) <= 10:
                raise ShardError('請提供 2 至 10 個預測選項。')
            labels = [text(label, '選項', 100) for label in labels]
            if len({label.casefold() for label in labels}) != len(labels):
                raise ShardError('預測選項不可重複。')
            market_id = new_record_id()
            tx.insert('prediction_market', {'id': market_id, 'name': name, 'description': description,
                'closesAt': closes, 'settlesAt': settles, 'baseReward': base, 'status': 'active',
                'createdBy': user_id, 'version': 1, 'createdAt': now, 'updatedAt': now})
            for index, label in enumerate(labels):
                tx.insert('prediction_option', {'id': new_record_id(), 'marketId': market_id, 'label': label, 'position': index})
            detail = {'baseAdded': base, 'metadata': data}
        else:
            market = get_market(tx, market_id)
            if market['status'] != 'active':
                raise ShardError('此預測盤已完成結算或取消。')
            if action == 'bet':
                if now >= market['closesAt']:
                    raise ShardError('此預測盤已截止押注。')
                option_id = data.get('optionId')
                if not isinstance(option_id, str) or not tx.select('prediction_option', {'id': option_id, 'marketId': market_id}):
                    raise ShardError('請選擇此預測盤的有效選項。')
                amount = integer(data.get('amount'))
                total = tx.query('SELECT coalesce(sum(amount), 0) AS total FROM prediction_bet WHERE marketId=?', (market_id,))[0]['total']
                if total + amount + market['baseReward'] > MAX_AMOUNT:
                    raise ShardError('預測盤池額超過上限。')
                bet_id = new_record_id()
                record = append_entry(tx, user_id, -amount, 'prediction_bet', bet_id, f"預測押注：{market['name']}")
                tx.insert('prediction_bet', {'id': bet_id, 'marketId': market_id, 'optionId': option_id,
                    'userId': user_id, 'amount': amount, 'recordId': record, 'createdAt': now})
                detail = {'betId': bet_id, 'optionId': option_id, 'amount': amount}
            else:
                if type(data.get('version')) is not int or data['version'] != market['version']:
                    raise ShardError('預測盤資訊已更新，請重新載入後操作。')
                if action == 'edit':
                    if 'options' in data:
                        raise ShardError('建立後不可修改預測選項。')
                    name = text(data.get('name', market['name']), '名稱', 120)
                    description = text(data.get('description', market['description']), '說明', 2000, empty=True)
                    closes = timestamp(data.get('closesAt', market['closesAt']))
                    settles = timestamp(data.get('settlesAt', market['settlesAt']))
                    if closes != market['closesAt'] and (market['closesAt'] <= now or closes <= now):
                        raise ShardError('不可修改已截止的押注時間，也不可把截止時間改到過去。')
                    if settles < closes or (settles != market['settlesAt'] and settles < now):
                        raise ShardError('結算時間不得早於截止時間或現在。')
                    base = integer(data.get('baseReward', market['baseReward']), zero=True)
                    if base < market['baseReward']:
                        raise ShardError('基礎獎勵只能增加，不可減少。')
                    if base > market['baseReward'] and role != 'web_admin':
                        raise PermissionError('只有網頁管理員可添加基礎獎勵。')
                    total = tx.query('SELECT coalesce(sum(amount), 0) AS total FROM prediction_bet WHERE marketId=?', (market_id,))[0]['total']
                    if total + base > MAX_AMOUNT:
                        raise ShardError('預測盤池額超過上限。')
                    values = {'name': name, 'description': description, 'closesAt': closes, 'settlesAt': settles, 'baseReward': base,
                              'version': market['version'] + 1, 'updatedAt': now}
                    tx.update('prediction_market', values, {'id': market_id})
                    detail = {'before': market, 'after': values, 'baseAdded': base - market['baseReward']}
                elif action in ('settle', 'cancel'):
                    if action == 'settle' and now < market['settlesAt']:
                        raise ShardError('尚未到結算時間。')
                    winner = data.get('winnerId') if action == 'settle' else None
                    if action == 'settle' and (not isinstance(winner, str) or not tx.select('prediction_option', {'id': winner, 'marketId': market_id})):
                        raise ShardError('請選擇有效的獲勝選項。')
                    stakes = tx.query('SELECT userId, optionId, sum(amount) AS amount FROM prediction_bet WHERE marketId=? GROUP BY userId, optionId', (market_id,))
                    weights = {row['userId']: row['amount'] for row in stakes if row['optionId'] == winner}
                    refund = action == 'cancel' or not weights
                    pool = sum(row['amount'] for row in stakes) + market['baseReward']
                    if refund:
                        payouts = {}
                        for row in stakes:
                            payouts[row['userId']] = payouts.get(row['userId'], 0) + row['amount']
                    else:
                        payouts = proportional(weights, pool)
                    for recipient, amount in payouts.items():
                        if not amount:
                            continue
                        payout_id = new_record_id()
                        kind = 'prediction_refund' if refund else 'prediction_reward'
                        label = '預測退款' if refund else '預測結算（含本金）'
                        record = append_entry(tx, recipient, amount, kind, payout_id, f"{label}：{market['name']}")
                        tx.insert('prediction_payout', {'id': payout_id, 'marketId': market_id, 'userId': recipient,
                            'amount': amount, 'kind': kind, 'recordId': record, 'createdAt': now})
                    tx.update('prediction_market', {'status': 'cancelled' if action == 'cancel' else 'settled',
                        'winnerId': winner, 'settlementMode': 'refund' if refund else 'payout', 'settledBy': user_id,
                        'settledAt': now, 'updatedAt': now, 'version': market['version'] + 1}, {'id': market_id})
                    detail = {'winnerId': winner, 'refunded': refund, 'distributed': sum(payouts.values()),
                              'unusedBaseReward': market['baseReward'] if refund else 0}
                else:
                    raise ShardError('無效的操作。')
        tx.insert('prediction_event', {'id': new_record_id(), 'marketId': market_id, 'userId': user_id,
            'requestId': request_id, 'action': action, 'fingerprint': fingerprint,
            'detail': json.dumps(detail, ensure_ascii=False), 'createdAt': now})
        return market_view(tx, get_market(tx, market_id), user_id, now)
