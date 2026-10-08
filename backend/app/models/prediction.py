"""Atomic pooled predictions, immutable options, integer payouts and audited commands."""
import json
import math
import time

from app.models.record_ids import new_record_id
from app.models.star_shard import MAX_AMOUNT, ShardError, append_entry, balance, ensure_schema as ensure_ledger


def ensure_schema(tx):
    """Create markets, immutable choices, stakes, payouts and idempotent audit events.
    初始化或遷移預測盤、固定選項、下注、派款與操作事件及必要索引與約束。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = ensure_schema(tx=tx)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return PredictionRepository(tx).ensure_schema()


def get_market(tx, market_id):
    """Read one market or raise a public validation error.
    取得指定預測盤，找不到時拋出公開驗證錯誤。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。
        market_id: 預測盤 UUID；建立操作可使用 None。

    Returns:
        dict: 指定預測盤的資料列。

    Exceptions:
        ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = get_market(tx=tx, market_id=market_id)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return PredictionRepository(tx).get_market(market_id)


def market_view(tx, market, user_id, now):
    """Calculate current gross odds and own stakes, without exposing other bettors.
    計算預測盤階段、含本金賠率及本人押注與派款金額。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。
        market: 已讀取的預測盤資料對照表。
        user_id: Discord 使用者 ID 字串。
        now: Unix 秒數；支援 None 的函式會使用目前時間。

    Returns:
        dict: 預測盤資訊、階段、選項賠率與本人押注及領回金額。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = market_view(tx=tx, market=market, user_id="123456789012345678", now=now)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return PredictionRepository(tx).market_view(market, user_id, now)


def text(value, label, limit, *, empty=False):
    """Validate bounded, human-readable metadata without interpreting markup.
    驗證並整理具有長度限制的預測盤文字。

    Args:
        value: 待驗證或轉換的值。
        label: 驗證錯誤中使用的欄位名稱。
        limit: 整理後文字允許的最大字元數。
        empty: 是否允許整理後的文字為空字串。 預設為 False。

    Returns:
        str: 去除頭尾空白且通過驗證的文字。

    Exceptions:
        ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> result = text(value=value, label="名稱", limit=limit)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    if not isinstance(value, str) or len(value.strip()) > limit or (not empty and not value.strip()):
        raise ShardError(f'{label}格式不正確（最多 {limit} 字）。')
    return value.strip()


def timestamp(value):
    """Accept finite Unix seconds representable by the browser date controls.
    驗證可由瀏覽器表示的有限 Unix 秒數。

    Args:
        value: 待驗證或轉換的值。

    Returns:
        int | float: 通過驗證的 Unix 秒數。

    Exceptions:
        ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> result = timestamp(value=value)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 253402300800:
        raise ShardError('請提供有效的截止與結算時間。')
    return value


def integer(value, *, zero=False):
    """Require integer shard amounts within the ledger's safe numeric range.
    驗證碎片金額為安全範圍內的整數。

    Args:
        value: 待驗證或轉換的值。
        zero: 是否允許整數金額為零。 預設為 False。

    Returns:
        int: 通過安全範圍驗證的整數金額。

    Exceptions:
        ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> result = integer(value=value)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    if type(value) is not int or not (0 if zero else 1) <= value <= MAX_AMOUNT:
        raise ShardError('星之碎片數量必須為有效整數。')
    return value


def proportional(weights, pool):
    """Allocate the exact integer pool using largest remainders aggregated per user.
    依使用者權重以最大餘數法分配完整整數池額，同餘數按使用者 ID 排序。

    Args:
        weights: 使用者 ID 與正整數權重的對照表，須非空。
        pool: 要完整分配的整數池額。

    Returns:
        dict[str, int]: 每位使用者的分配金額，總和等於 pool。

    Example:
        >>> result = proportional(weights={"user_a": 1, "user_b": 2}, pool=30)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    total = sum(weights.values())
    allocations = {user: pool * amount // total for user, amount in weights.items()}
    remaining = pool - sum(allocations.values())
    order = sorted(weights, key=lambda user: (-(pool * weights[user] % total), user))
    for user in order[:remaining]:
        allocations[user] += 1
    return allocations


def execute(db, user_id, request_id, action, data, *, market_id=None, role=None, now=None):
    """Commit one intent with all ledger effects, rejecting stale administrative edits.
    在同一即時交易內執行預測盤操作與帳本異動，拒絕過期版本及衝突重試。

    Args:
        db: 提供 transaction 方法的 SQLManager。
        user_id: Discord 使用者 ID 字串。
        request_id: 此操作的冪等識別碼；重試時須沿用相同值。
        action: 要執行的操作名稱。
        data: 操作內容；建立需 name、options、closesAt、settlesAt，押注需 optionId、amount，管理異動需 version。
        market_id: 預測盤 UUID；建立操作可使用 None。 預設為 None。
        role: 經驗證的管理身份 key，限 admin 或 web_admin 可管理。 預設為 None。
        now: Unix 秒數；支援 None 的函式會使用目前時間。 預設為 None。

    Returns:
        dict: 預測盤資訊、階段、選項賠率與本人押注及領回金額。

    Exceptions:
        PermissionError: 目前身份無權執行管理或添加基礎獎勵。 若由下列處理流程捕捉，則依其轉換規則處理。
        ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> result = execute(db=db, user_id="123456789012345678", request_id="00000000-0000-4000-8000-000000000001", action=action, data=data)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return PredictionService(db).execute(user_id, request_id, action, data, market_id=market_id, role=role, now=now)


class PredictionRepository:
    """Own prediction storage and bettor-specific read views.
    封裝預測盤結構、查詢與本人押注檢視。
    """

    def __init__(self, tx):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            tx: 目前交易的 SQLSession，物件不得超出該交易生命週期。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = PredictionRepository(tx)
            相依項目須先依 Args 建立。
        """
        self.tx = tx

    def ensure_schema(self):
        """Create markets, immutable choices, stakes, payouts and idempotent audit events.
        初始化或遷移預測盤、固定選項、下注、派款與操作事件及必要索引與約束。

        Args:
            None: 依物件初始化時的相依項目執行。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = PredictionRepository(tx)
            ...     result = service.ensure_schema()
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
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

    def get_market(self, market_id):
        """Read one market or raise a public validation error.
        取得指定預測盤，找不到時拋出公開驗證錯誤。

        Args:
            market_id: 預測盤 UUID；建立操作可使用 None。

        Returns:
            dict: 指定預測盤的資料列。

        Exceptions:
            ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = PredictionRepository(tx)
            ...     result = service.get_market(market_id=market_id)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
        rows = tx.select('prediction_market', {'id': market_id}) if isinstance(market_id, str) else []
        if not rows:
            raise ShardError('找不到預測盤。')
        return rows[0]

    def market_view(self, market, user_id, now):
        """Calculate current gross odds and own stakes, without exposing other bettors.
        計算預測盤階段、含本金賠率及本人押注與派款金額。

        Args:
            market: 已讀取的預測盤資料對照表。
            user_id: Discord 使用者 ID 字串。
            now: Unix 秒數；支援 None 的函式會使用目前時間。

        Returns:
            dict: 預測盤資訊、階段、選項賠率與本人押注及領回金額。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = PredictionRepository(tx)
            ...     result = service.market_view(market=market, user_id=user_id, now=now)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
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


class PredictionService:
    """Coordinate authorized prediction commands and complete settlement transactions.
    管理預測操作、權限約束與完整结算交易。
    """

    def __init__(self, db):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            db: 此服務所使用的 SQLManager；各寫入方法自行管理原子交易。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = PredictionService(db)
            相依項目須先依 Args 建立。
        """
        self.db = db

    def execute(self, user_id, request_id, action, data, *, market_id=None, role=None, now=None):
        """Commit one intent with all ledger effects, rejecting stale administrative edits.
        在同一即時交易內執行預測盤操作與帳本異動，拒絕過期版本及衝突重試。

        Args:
            user_id: Discord 使用者 ID 字串。
            request_id: 此操作的冪等識別碼；重試時須沿用相同值。
            action: 要執行的操作名稱。
            data: 操作內容；建立需 name、options、closesAt、settlesAt，押注需 optionId、amount，管理異動需 version。
            market_id: 預測盤 UUID；建立操作可使用 None。 預設為 None。
            role: 經驗證的管理身份 key，限 admin 或 web_admin 可管理。 預設為 None。
            now: Unix 秒數；支援 None 的函式會使用目前時間。 預設為 None。

        Returns:
            dict: 預測盤資訊、階段、選項賠率與本人押注及領回金額。

        Exceptions:
            PermissionError: 目前身份無權執行管理或添加基礎獎勵。 若由下列處理流程捕捉，則依其轉換規則處理。
            ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> service = PredictionService(db)
            >>> result = service.execute(user_id=user_id, request_id=request_id, action=action, data=data)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        db = self.db
        if action != 'bet' and role not in ('admin', 'web_admin'):
            raise PermissionError('僅限管理員以上操作。')
        fingerprint = json.dumps([action, market_id, data], sort_keys=True, ensure_ascii=False)
        with db.transaction(immediate=True) as tx:
            repository = PredictionRepository(tx)
            repository.ensure_schema()
            now = time.time() if now is None else now
            previous = tx.select('prediction_event', {'userId': user_id, 'requestId': request_id})
            if previous:
                if previous[0]['fingerprint'] != fingerprint:
                    raise ShardError('操作識別碼已使用，請重新確認。')
                return repository.market_view(repository.get_market(previous[0]['marketId']), user_id, now)
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
                market = repository.get_market(market_id)
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
            return repository.market_view(repository.get_market(market_id), user_id, now)
