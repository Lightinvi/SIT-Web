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
from app.models.star_shard import append_entry, balance, ensure_schema as ensure_ledger, ShardError, ShardLedger


def ensure_schema(tx):
    """Create durable shoes, rounds and idempotency receipts in the caller's transaction.
    初始化或遷移共享牌靴、牌局與操作憑證及必要索引與約束。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = ensure_schema(tx=tx)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return BlackjackShoe(tx).ensure_schema()


def hand(cards):
    """Build the library's hand evaluator from persisted card identities.
    依儲存的牌面建立撲克牌函式庫的手牌評分物件。

    Args:
        cards: 含 face 的儲存牌面清單。

    Returns:
        Hand: 可計算點數及分牌資格的手牌物件。

    Example:
        >>> result = hand(cards=cards)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    result = Hand()
    for card in cards:
        result.push(Card(card['face']))
    return result


def natural(cards):
    """Only an original two-card 21 qualifies as a natural blackjack.
    判斷原始兩張牌是否合計二十一點。

    Args:
        cards: 含 face 的儲存牌面清單。

    Returns:
        bool: 是否為原始兩張牌的二十一點。

    Example:
        >>> result = natural(cards=cards)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return len(cards) == 2 and hand(cards).count() == 21


def draw(tx):
    """Consume exactly one shared shoe position, refilling only after all 260 draws.
    消耗共享牌靴的一張牌，全部二百六十張發完後才重新洗牌。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。

    Returns:
        dict: 含唯一牌位 id 與 face 的牌。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = draw(tx=tx)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return BlackjackShoe(tx).draw()


def debit(tx, state, amount, description):
    """Debit a stake atomically, tracking total exposure for final net results.
    扣除牌局下注並累加總投入金額。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。
        state: 目前遊戲狀態對照表。
        amount: 要扣除或發放的正整數碎片數量。
        description: 顯示於紀錄的說明文字。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = debit(tx=tx, state=state, amount=10, description="Example reward")
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return BlackjackRound(tx, state).debit(amount, description)


def settle(tx, state, *, peek=False):
    """Play S17 dealer when necessary and credit gross returns exactly once.
    依美式 soft 17 停牌規則執行莊家操作並結算含本金的返還金額。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。
        state: 目前遊戲狀態對照表。
        peek: 是否使用已偷看暗牌的立即結算流程。 預設為 False。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = settle(tx=tx, state=state)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return BlackjackRound(tx, state).settle(peek=peek)


def after_peek(tx, state):
    """Resolve dealer naturals before player actions, and pay original player naturals.
    在玩家行動前處理莊家或玩家的原始 Blackjack。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。
        state: 目前遊戲狀態對照表。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = after_peek(tx=tx, state=state)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return BlackjackRound(tx, state).after_peek()


def advance(tx, state):
    """Advance through completed split hands or finish dealer play.
    切換至下一手尚未完成的分牌，全部完成後進入結算。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。
        state: 目前遊戲狀態對照表。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = advance(tx=tx, state=state)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return BlackjackRound(tx, state).advance()


def allowed(state, funds):
    """Return only legal actions that the current balance can fund.
    依目前牌局狀態與可用餘額列出合法動作。

    Args:
        state: 目前遊戲狀態對照表。
        funds: 使用者目前可用的整數碎片餘額。

    Returns:
        list[str]: 目前可執行且餘額足夠的動作。

    Example:
        >>> result = allowed(state=state, funds=100)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
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
    """Serialize only the requesting player's round, never the hole card or shoe order.
    回傳本人牌局與餘額，未結算時隱藏莊家暗牌且不公開牌靴順序。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。
        user_id: Discord 使用者 ID 字串。
        state: 目前遊戲狀態對照表。 預設為 None。

    Returns:
        dict: 餘額及本人牌局，未結算時隱藏莊家暗牌。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = public_state(tx=tx, user_id="123456789012345678")
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return BlackjackRepository(tx).public_state(user_id, state)


def play(db, user_id, request_id, action, *, bet=None, round_id=None, version=None):
    """Serialize shared draws and ledger writes, rejecting stale or conflicting commands.
    以即時交易處理共享發牌、下注及結算，拒絕過期或衝突的操作。

    Args:
        db: 提供 transaction 方法的 SQLManager。
        user_id: Discord 使用者 ID 字串。
        request_id: 此操作的冪等識別碼；重試時須沿用相同值。
        action: 要執行的操作名稱。
        bet: 原始下注金額，須為至少二點的正偶數。 預設為 None。
        round_id: 要操作的牌局 UUID。 預設為 None。
        version: 用戶端讀取的狀態版本，用於拒絕過期操作。 預設為 None。

    Returns:
        dict: 本人餘額與隱藏暗牌後的牌局狀態。

    Exceptions:
        ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> result = play(db=db, user_id="123456789012345678", request_id="00000000-0000-4000-8000-000000000001", action=action)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return BlackjackService(db).play(user_id, request_id, action, bet=bet, round_id=round_id, version=version)


class BlackjackShoe:
    """Own durable shared-shoe storage and card consumption.
    管理共享牌靴結構與唯一牌位的消耗。
    """

    def __init__(self, tx):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            tx: 目前交易的 SQLSession，物件不得超出該交易生命週期。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = BlackjackShoe(tx)
            相依項目須先依 Args 建立。
        """
        self.tx = tx

    def ensure_schema(self):
        """Create durable shoes, rounds and idempotency receipts in the caller's transaction.
        初始化或遷移共享牌靴、牌局與操作憑證及必要索引與約束。

        Args:
            None: 依物件初始化時的相依項目執行。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = BlackjackShoe(tx)
            ...     result = service.ensure_schema()
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
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

    def draw(self):
        """Consume exactly one shared shoe position, refilling only after all 260 draws.
        消耗共享牌靴的一張牌，全部二百六十張發完後才重新洗牌。

        Args:
            None: 依物件初始化時的相依項目執行。

        Returns:
            dict: 含唯一牌位 id 與 face 的牌。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = BlackjackShoe(tx)
            ...     result = service.draw()
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
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


class BlackjackRound:
    """Encapsulate one mutable round and its transactional accounting.
    封裝單一牌局的狀態推進、下注與結算。
    """

    def __init__(self, tx, state):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            tx: 目前交易的 SQLSession，物件不得超出該交易生命週期。
            state: 本牌局的可變狀態對照表，狀態推進會原地更新此物件。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = BlackjackRound(tx, state)
            相依項目須先依 Args 建立。
        """
        self.tx = tx
        self.state = state
        self.ledger = ShardLedger(tx)
        self.shoe = BlackjackShoe(tx)

    def debit(self, amount, description):
        """Debit a stake atomically, tracking total exposure for final net results.
        扣除牌局下注並累加總投入金額。

        Args:
            amount: 要扣除或發放的正整數碎片數量。
            description: 顯示於紀錄的說明文字。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = BlackjackRound(tx, state)
            ...     result = service.debit(amount=amount, description=description)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
        state = self.state
        self.ledger.append_entry(state['userId'], -amount, 'blackjack', state['id'], description)
        state['staked'] += amount

    def settle(self, *, peek=False):
        """Play S17 dealer when necessary and credit gross returns exactly once.
        依美式 soft 17 停牌規則執行莊家操作並結算含本金的返還金額。

        Args:
            peek: 是否使用已偷看暗牌的立即結算流程。 預設為 False。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = BlackjackRound(tx, state)
            ...     result = service.settle()
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
        state = self.state
        if state['phase'] == 'settled':
            return
        dealer = state['dealer']
        hands = state['hands']
        if not peek and any(hand(item['cards']).count() <= 21 for item in hands):
            while hand(dealer).count() < 17:
                dealer.append(self.shoe.draw())
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
            self.ledger.append_entry(state['userId'], payout, 'blackjack', state['id'], '21 點結算（含退回本金）')
        state.update(phase='settled', payout=payout, net=payout - state['staked'])

    def after_peek(self):
        """Resolve dealer naturals before player actions, and pay original player naturals.
        在玩家行動前處理莊家或玩家的原始 Blackjack。

        Args:
            None: 依物件初始化時的相依項目執行。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = BlackjackRound(tx, state)
            ...     result = service.after_peek()
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
        state = self.state
        if natural(state['dealer']) or natural(state['hands'][0]['cards']):
            self.settle(peek=True)
        else:
            state['phase'] = 'player'

    def advance(self):
        """Advance through completed split hands or finish dealer play.
        切換至下一手尚未完成的分牌，全部完成後進入結算。

        Args:
            None: 依物件初始化時的相依項目執行。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = BlackjackRound(tx, state)
            ...     result = service.advance()
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
        state = self.state
        for index, item in enumerate(state['hands']):
            if hand(item['cards']).count() >= 21:
                item['done'] = True
            if not item['done']:
                state['activeHand'] = index
                return
        self.settle()


class BlackjackRepository:
    """Read a player-safe view without revealing hidden game data.
    在交易內產生只包含本人且隱藏暗牌的牌局檢視。
    """

    def __init__(self, tx):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            tx: 目前交易的 SQLSession，物件不得超出該交易生命週期。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = BlackjackRepository(tx)
            相依項目須先依 Args 建立。
        """
        self.tx = tx

    def public_state(self, user_id, state=None):
        """Serialize only the requesting player's round, never the hole card or shoe order.
        回傳本人牌局與餘額，未結算時隱藏莊家暗牌且不公開牌靴順序。

        Args:
            user_id: Discord 使用者 ID 字串。
            state: 目前遊戲狀態對照表。 預設為 None。

        Returns:
            dict: 餘額及本人牌局，未結算時隱藏莊家暗牌。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = BlackjackRepository(tx)
            ...     result = service.public_state(user_id=user_id)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
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


class BlackjackService:
    """Coordinate versioned commands, shared cards and atomic ledger changes.
    協調版本化牌局操作、共享發牌與原子帳本異動。
    """

    def __init__(self, db):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            db: 此服務所使用的 SQLManager；各寫入方法自行管理原子交易。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = BlackjackService(db)
            相依項目須先依 Args 建立。
        """
        self.db = db

    def play(self, user_id, request_id, action, *, bet=None, round_id=None, version=None):
        """Serialize shared draws and ledger writes, rejecting stale or conflicting commands.
        以即時交易處理共享發牌、下注及結算，拒絕過期或衝突的操作。

        Args:
            user_id: Discord 使用者 ID 字串。
            request_id: 此操作的冪等識別碼；重試時須沿用相同值。
            action: 要執行的操作名稱。
            bet: 原始下注金額，須為至少二點的正偶數。 預設為 None。
            round_id: 要操作的牌局 UUID。 預設為 None。
            version: 用戶端讀取的狀態版本，用於拒絕過期操作。 預設為 None。

        Returns:
            dict: 本人餘額與隱藏暗牌後的牌局狀態。

        Exceptions:
            ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> service = BlackjackService(db)
            >>> result = service.play(user_id=user_id, request_id=request_id, action=action)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        db = self.db
        fingerprint = json.dumps([action, bet, round_id, version])
        with db.transaction(immediate=True) as tx:
            shoe = BlackjackShoe(tx)
            shoe.ensure_schema()
            repository = BlackjackRepository(tx)
            receipts = tx.select('blackjack_request', {'userId': user_id, 'requestId': request_id})
            if receipts:
                if receipts[0]['fingerprint'] != fingerprint:
                    raise ShardError('此操作識別碼已用於其他操作，請重新確認牌局。')
                return repository.public_state(user_id)
            if action == 'start':
                if type(bet) is not int or bet < 2 or bet % 2 or bet > balance(tx, user_id):
                    raise ShardError('下注須為至少 2 點的正偶數，且不可超過餘額。')
                if tx.query("SELECT id FROM blackjack_round WHERE userId=? AND status != 'settled'", (user_id,)):
                    raise ShardError('請先完成目前的牌局。')
                state = {'id': new_record_id(), 'userId': user_id, 'version': 1, 'phase': 'player',
                         'baseBet': bet, 'staked': 0, 'insurance': 0, 'activeHand': 0,
                         'hands': [{'cards': [], 'bet': bet, 'done': False, 'split': False}], 'dealer': []}
                round_object = BlackjackRound(tx, state)
                round_object.debit(bet, '21 點下注')
                for _ in range(2):
                    state['hands'][0]['cards'].append(shoe.draw())
                    state['dealer'].append(shoe.draw())
                if state['dealer'][0]['face'].startswith('A'):
                    state['phase'] = 'insurance'
                else:
                    round_object.after_peek()
                timestamp = time.time()
                tx.insert('blackjack_round', {'id': state['id'], 'userId': user_id, 'state': json.dumps(state),
                          'status': state['phase'], 'createdAt': timestamp, 'updatedAt': timestamp})
            else:
                rows = tx.select('blackjack_round', {'id': round_id, 'userId': user_id}) if isinstance(round_id, str) else []
                if not rows:
                    raise ShardError('找不到牌局，請重新確認。')
                state = json.loads(rows[0]['state'])
                round_object = BlackjackRound(tx, state)
                if type(version) is not int or version != state['version']:
                    raise ShardError('牌局已更新，請重新確認後操作。')
                if action not in allowed(state, balance(tx, user_id)):
                    raise ShardError('目前不能執行此操作，或星之碎片不足。')
                if action in ('insurance', 'decline'):
                    if action == 'insurance':
                        state['insurance'] = state['baseBet'] // 2
                        round_object.debit(state['insurance'], '21 點保險')
                    round_object.after_peek()
                else:
                    item = state['hands'][state['activeHand']]
                    if action == 'stand':
                        item['done'] = True
                    elif action == 'hit':
                        item['cards'].append(shoe.draw())
                    elif action == 'double':
                        round_object.debit(item['bet'], '21 點加倍下注')
                        item['bet'] *= 2
                        item['cards'].append(shoe.draw())
                        item['done'] = True
                    elif action == 'split':
                        round_object.debit(item['bet'], '21 點分牌下注')
                        second = {'cards': [item['cards'].pop()], 'bet': item['bet'], 'done': False, 'split': True}
                        item['split'] = True
                        split_aces = item['cards'][0]['face'].startswith('A')
                        item['cards'].append(shoe.draw())
                        second['cards'].append(shoe.draw())
                        item['done'] = second['done'] = split_aces
                        state['hands'].insert(state['activeHand'] + 1, second)
                    round_object.advance()
                state['version'] += 1
                tx.update('blackjack_round', {'state': json.dumps(state), 'status': state['phase'], 'updatedAt': time.time()}, {'id': state['id']})
            tx.insert('blackjack_request', {'id': new_record_id(), 'userId': user_id, 'requestId': request_id,
                      'fingerprint': fingerprint, 'roundId': state['id'], 'createdAt': time.time()})
            return repository.public_state(user_id, state)
