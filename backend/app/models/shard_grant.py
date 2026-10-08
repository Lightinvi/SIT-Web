"""Audited, idempotent administrator grants posted to the append-only shard ledger."""
import time

from app.models.record_ids import new_record_id
from app.models.star_shard import MAX_AMOUNT, ShardError, append_entry, ensure_schema


def grant(db, administrator_id, recipient_id, amount, request_id):
    """Atomically create a system credit and its administrator audit receipt.
    在同一交易內建立系統發放入帳及管理員稽核憑證。

    Args:
        db: 提供 transaction 方法的 SQLManager。
        administrator_id: 發放管理員的 Discord 使用者 ID。
        recipient_id: 接收者的 Discord 使用者 ID。
        amount: 要扣除或發放的正整數碎片數量。
        request_id: 此操作的冪等識別碼；重試時須沿用相同值。

    Returns:
        dict: 系統發放憑證，包含管理員、接收者、金額及帳本來源。

    Exceptions:
        ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> result = grant(db=db, administrator_id="123456789012345678", recipient_id="223456789012345678", amount=10, request_id="00000000-0000-4000-8000-000000000001")
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return ShardGrantService(db).grant(administrator_id, recipient_id, amount, request_id)


class ShardGrantService:
    """Coordinate audited system grants using one database.
    管理系統發放、帳本入帳與管理員稽核交易。
    """

    def __init__(self, db):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            db: 此服務所使用的 SQLManager；各寫入方法自行管理原子交易。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = ShardGrantService(db)
            相依項目須先依 Args 建立。
        """
        self.db = db

    def grant(self, administrator_id, recipient_id, amount, request_id):
        """Atomically create a system credit and its administrator audit receipt.
        在同一交易內建立系統發放入帳及管理員稽核憑證。

        Args:
            administrator_id: 發放管理員的 Discord 使用者 ID。
            recipient_id: 接收者的 Discord 使用者 ID。
            amount: 要扣除或發放的正整數碎片數量。
            request_id: 此操作的冪等識別碼；重試時須沿用相同值。

        Returns:
            dict: 系統發放憑證，包含管理員、接收者、金額及帳本來源。

        Exceptions:
            ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> service = ShardGrantService(db)
            >>> result = service.grant(administrator_id=administrator_id, recipient_id=recipient_id, amount=amount, request_id=request_id)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        db = self.db
        if not isinstance(recipient_id, str) or not recipient_id:
            raise ShardError('請選擇發放對象。')
        if type(amount) is not int or not 0 < amount <= MAX_AMOUNT:
            raise ShardError('發放數量必須為有效的正整數。')
        with db.transaction(immediate=True) as tx:
            ensure_schema(tx)
            tx.execute('''CREATE TABLE IF NOT EXISTS star_shard_grant (
                id TEXT PRIMARY KEY NOT NULL,
                administratorId TEXT NOT NULL REFERENCES member(userId),
                userId TEXT NOT NULL REFERENCES member(userId),
                amount INTEGER NOT NULL CHECK(typeof(amount) = 'integer' AND amount > 0),
                requestId TEXT NOT NULL, recordId TEXT NOT NULL REFERENCES star_shard(id),
                createdAt REAL NOT NULL, UNIQUE(administratorId, requestId))''')
            previous = tx.select('star_shard_grant', {'administratorId': administrator_id, 'requestId': request_id})
            if previous:
                receipt = previous[0]
                if (receipt['userId'], receipt['amount']) != (recipient_id, amount):
                    raise ShardError('此操作已用於其他發放，請重新確認。')
                return receipt
            grant_id = new_record_id()
            record_id = append_entry(tx, recipient_id, amount, 'system', grant_id, '系統發放')
            receipt = {'id': grant_id, 'administratorId': administrator_id, 'userId': recipient_id,
                       'amount': amount, 'requestId': request_id, 'recordId': record_id, 'createdAt': time.time()}
            tx.insert('star_shard_grant', receipt)
            return receipt
