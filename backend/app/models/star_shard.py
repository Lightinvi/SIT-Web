"""Append-only Star Shard ledger with serialized, retry-safe member transfers."""
import time

from app.models.member import MemberProfileStore
from app.models.record_ids import RecordSchemaManager, new_record_id

MAX_AMOUNT = 9_007_199_254_740_991


class ShardError(ValueError):
    """Represent a rejected ledger operation that has not changed any balances."""


def ensure_schema(tx):
    """Create ledger, balance lookup index, and transfer idempotency receipts.
    初始化或遷移碎片帳本與轉讓憑證及必要索引與約束。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = ensure_schema(tx=tx)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return ShardLedger(tx).ensure_schema()


def balance(tx, user_id):
    """Read the latest committed ledger sequence, returning zero for new members.
    依最新帳本序號取得成員餘額，無紀錄時回傳零。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。
        user_id: Discord 使用者 ID 字串。

    Returns:
        int: 最新帳本餘額，無紀錄時為零。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = balance(tx=tx, user_id="123456789012345678")
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return ShardLedger(tx).balance(user_id)


def append_entry(tx, user_id, amount, transaction_type, source, description):
    """Append a signed integer adjustment inside a caller-owned immediate transaction.

    Trusted future reward/game services may call this after validating their own
    authorization and event idempotency; this is never exposed as a public mint API.
    在呼叫者的即時交易內新增帶正負號的碎片帳本紀錄，檢查成員及餘額上限。

    Args:
        tx: 目前交易的 SQLSession；由呼叫者管理提交與回滾。
        user_id: Discord 使用者 ID 字串。
        amount: 非零帶正負號的整數碎片異動，正值入帳、負值扣款。
        transaction_type: 帳本交易類型。
        source: 對應業務紀錄或使用者的來源識別碼。
        description: 顯示於紀錄的說明文字。

    Returns:
        str: 新增帳本紀錄的 UUID。

    Exceptions:
        ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> with db.transaction(immediate=True) as tx:
        ...     result = append_entry(tx=tx, user_id="123456789012345678", amount=10, transaction_type="system", source="00000000-0000-4000-8000-000000000002", description="Example reward")
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return ShardLedger(tx).append_entry(user_id, amount, transaction_type, source, description)


def transfer(db, sender, recipient, amount, request_id):
    """Commit paired debit/credit entries atomically and replay identical requests once.
    在同一交易內完成轉出、轉入與重試憑證，相同操作僅記帳一次。

    Args:
        db: 提供 transaction 方法的 SQLManager。
        sender: 轉出者的 Discord 使用者 ID。
        recipient: 接收者的 Discord 使用者 ID。
        amount: 要扣除或發放的正整數碎片數量。
        request_id: 此操作的冪等識別碼；重試時須沿用相同值。

    Returns:
        dict: 轉出者最新 balance 與扣款 recordId。

    Exceptions:
        ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> result = transfer(db=db, sender="123456789012345678", recipient="223456789012345678", amount=10, request_id="00000000-0000-4000-8000-000000000001")
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return ShardTransferService(db).transfer(sender, recipient, amount, request_id)


class ShardLedger:
    """Own ledger reads and writes within a transaction.
    封裝單一交易中的碎片帳本查詢與入帳約束。
    """

    def __init__(self, tx):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            tx: 目前交易的 SQLSession，物件不得超出該交易生命週期。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = ShardLedger(tx)
            相依項目須先依 Args 建立。
        """
        self.tx = tx
        self.profiles = MemberProfileStore(tx)
        self.schemas = RecordSchemaManager(tx)

    def ensure_schema(self):
        """Create ledger, balance lookup index, and transfer idempotency receipts.
        初始化或遷移碎片帳本與轉讓憑證及必要索引與約束。

        Args:
            None: 依物件初始化時的相依項目執行。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = ShardLedger(tx)
            ...     result = service.ensure_schema()
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
        self.profiles.ensure_member_schema()
        self.schemas.migrate_record_ids()
        self.schemas.create_record_table('star_shard')
        self.schemas.create_record_table('star_shard_request')

    def balance(self, user_id):
        """Read the latest committed ledger sequence, returning zero for new members.
        依最新帳本序號取得成員餘額，無紀錄時回傳零。

        Args:
            user_id: Discord 使用者 ID 字串。

        Returns:
            int: 最新帳本餘額，無紀錄時為零。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = ShardLedger(tx)
            ...     result = service.balance(user_id=user_id)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
        rows = tx.select('star_shard', {'userId': user_id}, order_by='sequence', descending=True, limit=1)
        return rows[0]['afterBlance'] if rows else 0

    def append_entry(self, user_id, amount, transaction_type, source, description):
        """Append a signed integer adjustment inside a caller-owned immediate transaction.

        Trusted future reward/game services may call this after validating their own
        authorization and event idempotency; this is never exposed as a public mint API.
        在呼叫者的即時交易內新增帶正負號的碎片帳本紀錄，檢查成員及餘額上限。

        Args:
            user_id: Discord 使用者 ID 字串。
            amount: 非零帶正負號的整數碎片異動，正值入帳、負值扣款。
            transaction_type: 帳本交易類型。
            source: 對應業務紀錄或使用者的來源識別碼。
            description: 顯示於紀錄的說明文字。

        Returns:
            str: 新增帳本紀錄的 UUID。

        Exceptions:
            ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> with db.transaction(immediate=True) as tx:
            ...     service = ShardLedger(tx)
            ...     result = service.append_entry(user_id=user_id, amount=amount, transaction_type=transaction_type, source=source, description=description)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        tx = self.tx
        if type(amount) is not int or not 0 < abs(amount) <= MAX_AMOUNT:
            raise ShardError('數量必須為非零整數。')
        if not tx.select('member', {'userId': user_id}):
            raise ShardError('找不到成員。')
        before = self.balance(user_id)
        after = before + amount
        if after < 0:
            raise ShardError('星之碎片餘額不足。')
        if after > MAX_AMOUNT:
            raise ShardError('餘額超過上限。')
        record_id = new_record_id()
        sequence = tx.query('SELECT coalesce(max(sequence), 0) + 1 AS next FROM star_shard')[0]['next']
        tx.insert('star_shard', {
            'id': record_id, 'sequence': sequence,
            'userId': user_id, 'amount': amount, 'beforeBlance': before, 'afterBlance': after,
            'transactionType': transaction_type, 'transactionSource': source,
            'description': description, 'createdAt': time.time(),
        })
        return record_id


class ShardTransferService:
    """Coordinate atomic member transfers with an injected database.
    透過注入的資料庫協調原子轉讓與冪等憑證。
    """

    def __init__(self, db):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            db: 此服務所使用的 SQLManager；各寫入方法自行管理原子交易。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = ShardTransferService(db)
            相依項目須先依 Args 建立。
        """
        self.db = db

    def transfer(self, sender, recipient, amount, request_id):
        """Commit paired debit/credit entries atomically and replay identical requests once.
        在同一交易內完成轉出、轉入與重試憑證，相同操作僅記帳一次。

        Args:
            sender: 轉出者的 Discord 使用者 ID。
            recipient: 接收者的 Discord 使用者 ID。
            amount: 要扣除或發放的正整數碎片數量。
            request_id: 此操作的冪等識別碼；重試時須沿用相同值。

        Returns:
            dict: 轉出者最新 balance 與扣款 recordId。

        Exceptions:
            ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> service = ShardTransferService(db)
            >>> result = service.transfer(sender=sender, recipient=recipient, amount=amount, request_id=request_id)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        db = self.db
        if not isinstance(recipient, str) or not recipient or recipient == sender:
            raise ShardError('請選擇其他成員。')
        if type(amount) is not int or not 0 < amount <= MAX_AMOUNT:
            raise ShardError('給予數量必須為正整數。')
        with db.transaction(immediate=True) as tx:
            ledger = ShardLedger(tx)
            ledger.ensure_schema()
            previous = tx.select('star_shard_request', {'userId': sender, 'requestId': request_id})
            if previous:
                if (previous[0]['recipientId'], previous[0]['amount']) != (recipient, amount):
                    raise ShardError('此操作已使用，請重新開啟給予視窗。')
                return {'balance': ledger.balance(sender), 'recordId': previous[0]['debitId']}
            debit = ledger.append_entry(sender, -amount, 'transaction', recipient, '給予成員星之碎片')
            credit = ledger.append_entry(recipient, amount, 'transaction', sender, '收到成員給予的星之碎片')
            tx.insert('star_shard_request', {'userId': sender, 'requestId': request_id,
                'recipientId': recipient, 'amount': amount, 'debitId': debit, 'creditId': credit})
            return {'balance': ledger.balance(sender), 'recordId': debit}
