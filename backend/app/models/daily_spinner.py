"""Once-per-system-local-day rewards recorded atomically with the shard ledger."""
from datetime import datetime, timedelta
import secrets
import time

from app.models.star_shard import append_entry, ensure_schema as ensure_ledger
from app.models.record_ids import create_record_table, new_record_id

BASE_REWARD = 10
PRIZES = (
    {'multiplier': 0.5, 'probability': 8, 'reward': 5},
    {'multiplier': 1, 'probability': 65, 'reward': 10},
    {'multiplier': 2, 'probability': 12, 'reward': 20},
    {'multiplier': 2.5, 'probability': 11, 'reward': 25},
    {'multiplier': 5, 'probability': 4, 'reward': 50},
)


def day_window(now):
    """Use the process's system timezone, including DST at the next local midnight.
    依主機本地日期取得當日與下一個午夜，支援夏令時間切換。

    Args:
        now: Unix 秒數；支援 None 的函式會使用目前時間。

    Returns:
        tuple[str, float]: 主機本地日期與下一午夜的 Unix 秒數。

    Example:
        >>> result = day_window(now=now)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    local = datetime.fromtimestamp(now)
    # Resolve each local midnight independently; DST days need not be 24 hours.
    midnight = datetime.combine(local.date() + timedelta(days=1), datetime.min.time())
    return local.date().isoformat(), midnight.timestamp()


def ensure_schema(tx):
    """Create immutable spin receipts with daily and retry uniqueness constraints.
    初始化或遷移不可修改的每日轉盤憑證及必要索引與約束。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = ensure_schema(tx=tx)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return SpinnerRepository(tx).ensure_schema()


def choose_prize():
    """Map 100 cryptographically random integer outcomes onto the published weights.
    依公布的機率，使用安全隨機整數選取轉盤獎勵。

    Args:
        None: 無需傳入參數。

    Returns:
        dict: 含倍率、機率及整數獎勵的設定。

    Exceptions:
        RuntimeError: 設定不一致或測試刻意注入的執行失敗。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> result = choose_prize()
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    roll = secrets.randbelow(100)
    cumulative = 0
    for prize in PRIZES:
        cumulative += prize['probability']
        if roll < cumulative:
            return prize
    raise RuntimeError('Invalid spinner probability configuration')


def public_state(now):
    """Expose the exact reward odds and server-owned daily reset boundary.
    公開轉盤獎勵機率與依主機時區計算的下一次刷新時間。

    Args:
        now: Unix 秒數；支援 None 的函式會使用目前時間。

    Returns:
        dict: 公布的轉盤機率、主機日期與下一次午夜刷新時間。

    Example:
        >>> result = public_state(now=now)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    day, reset = day_window(now)
    return {'day': day, 'nextResetAt': reset, 'serverTime': now,
            'timezone': time.strftime('%Z', time.localtime(now)),
            'baseReward': BASE_REWARD, 'prizes': list(PRIZES)}


def member_state(tx, user_id, now):
    """Return today's own receipt and eligibility without drawing or crediting anything.
    讀取成員當日轉盤紀錄與資格，不抽獎或派款。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。
        user_id: Discord 使用者 ID 字串。
        now: Unix 秒數；支援 None 的函式會使用目前時間。

    Returns:
        dict: 公開轉盤資訊與本人 todaySpin、canSpin。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = member_state(tx=tx, user_id="123456789012345678", now=now)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return SpinnerRepository(tx).member_state(user_id, now)


def spin(db, user_id, request_id, *, now=None):
    """Serialize a daily draw and ledger credit, replaying retries even across midnight.
    序列化每日抽獎與帳本派款，相同操作跨午夜重試也不重複派發。

    Args:
        db: 提供 transaction 方法的 SQLManager。
        user_id: Discord 使用者 ID 字串。
        request_id: 此操作的冪等識別碼；重試時須沿用相同值。
        now: Unix 秒數；支援 None 的函式會使用目前時間。 預設為 None。

    Returns:
        dict: 當日資格、抽獎結果及是否本次派款的 awarded 標記。

    Example:
        >>> result = spin(db=db, user_id="123456789012345678", request_id="00000000-0000-4000-8000-000000000001")
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return DailySpinnerService(db).spin(user_id, request_id, now=now)


class SpinnerRepository:
    """Read daily eligibility and initialize immutable spin storage.
    在交易內管理轉盤結構與個人當日資格。
    """

    def __init__(self, tx):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            tx: 目前交易的 SQLSession，物件不得超出該交易生命週期。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = SpinnerRepository(tx)
            相依項目須先依 Args 建立。
        """
        self.tx = tx

    def ensure_schema(self):
        """Create immutable spin receipts with daily and retry uniqueness constraints.
        初始化或遷移不可修改的每日轉盤憑證及必要索引與約束。

        Args:
            None: 依物件初始化時的相依項目執行。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = SpinnerRepository(tx)
            ...     result = service.ensure_schema()
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
        ensure_ledger(tx)
        create_record_table(tx, 'daily_spinner')

    def member_state(self, user_id, now):
        """Return today's own receipt and eligibility without drawing or crediting anything.
        讀取成員當日轉盤紀錄與資格，不抽獎或派款。

        Args:
            user_id: Discord 使用者 ID 字串。
            now: Unix 秒數；支援 None 的函式會使用目前時間。

        Returns:
            dict: 公開轉盤資訊與本人 todaySpin、canSpin。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = SpinnerRepository(tx)
            ...     result = service.member_state(user_id=user_id, now=now)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
        state = public_state(now)
        rows = tx.select('daily_spinner', {'userId': user_id, 'spinDate': state['day']})
        return {**state, 'todaySpin': rows[0] if rows else None, 'canSpin': not rows}


class DailySpinnerService:
    """Serialize daily rewards and ledger effects through one database.
    封裝每日抽獎與帳本派款的原子流程。
    """

    def __init__(self, db):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            db: 此服務所使用的 SQLManager；各寫入方法自行管理原子交易。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = DailySpinnerService(db)
            相依項目須先依 Args 建立。
        """
        self.db = db

    def spin(self, user_id, request_id, *, now=None):
        """Serialize a daily draw and ledger credit, replaying retries even across midnight.
        序列化每日抽獎與帳本派款，相同操作跨午夜重試也不重複派發。

        Args:
            user_id: Discord 使用者 ID 字串。
            request_id: 此操作的冪等識別碼；重試時須沿用相同值。
            now: Unix 秒數；支援 None 的函式會使用目前時間。 預設為 None。

        Returns:
            dict: 當日資格、抽獎結果及是否本次派款的 awarded 標記。

        Example:
            >>> service = DailySpinnerService(db)
            >>> result = service.spin(user_id=user_id, request_id=request_id)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        db = self.db
        with db.transaction(immediate=True) as tx:
            repository = SpinnerRepository(tx)
            repository.ensure_schema()
            timestamp = time.time() if now is None else now
            state = repository.member_state(user_id, timestamp)
            previous = tx.select('daily_spinner', {'userId': user_id, 'requestId': request_id})
            record = previous[0] if previous else state['todaySpin']
            if record:
                return {**state, 'result': record, 'awarded': False}
            prize = choose_prize()
            spin_id = new_record_id()
            tx.insert('daily_spinner', {
                'id': spin_id,
                'userId': user_id, 'spinDate': state['day'], 'requestId': request_id,
                'multiplier': prize['multiplier'], 'baseReward': BASE_REWARD,
                'reward': prize['reward'], 'createdAt': timestamp,
            })
            append_entry(tx, user_id, prize['reward'], 'daily_spinner', str(spin_id),
                         f"每日轉盤 {prize['multiplier']:g}x 獎勵")
            record = tx.select('daily_spinner', {'id': spin_id})[0]
            return {**state, 'canSpin': False, 'todaySpin': record, 'result': record, 'awarded': True}
