"""Audited, idempotent administrator grants posted to the append-only shard ledger."""
import time

from app.models.record_ids import new_record_id
from app.models.star_shard import MAX_AMOUNT, ShardError, append_entry, ensure_schema


def grant(db, administrator_id, recipient_id, amount, request_id):
    """Atomically create a system credit and its administrator audit receipt."""
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
