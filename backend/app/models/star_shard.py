"""Append-only Star Shard ledger with serialized, retry-safe member transfers."""
import time

from app.models.member import ensure_member_schema
from app.models.record_ids import create_record_table, migrate_record_ids, new_record_id

MAX_AMOUNT = 9_007_199_254_740_991


class ShardError(ValueError):
    """Represent a rejected ledger operation that has not changed any balances."""


def ensure_schema(tx):
    """Create ledger, balance lookup index, and transfer idempotency receipts."""
    ensure_member_schema(tx)
    migrate_record_ids(tx)
    create_record_table(tx, 'star_shard')
    create_record_table(tx, 'star_shard_request')


def balance(tx, user_id):
    """Read the latest committed ledger sequence, returning zero for new members."""
    rows = tx.select('star_shard', {'userId': user_id}, order_by='sequence', descending=True, limit=1)
    return rows[0]['afterBlance'] if rows else 0


def append_entry(tx, user_id, amount, transaction_type, source, description):
    """Append a signed integer adjustment inside a caller-owned immediate transaction.

    Trusted future reward/game services may call this after validating their own
    authorization and event idempotency; this is never exposed as a public mint API.
    """
    if type(amount) is not int or not 0 < abs(amount) <= MAX_AMOUNT:
        raise ShardError('數量必須為非零整數。')
    if not tx.select('member', {'userId': user_id}):
        raise ShardError('找不到成員。')
    before = balance(tx, user_id)
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


def transfer(db, sender, recipient, amount, request_id):
    """Commit paired debit/credit entries atomically and replay identical requests once."""
    if not isinstance(recipient, str) or not recipient or recipient == sender:
        raise ShardError('請選擇其他成員。')
    if type(amount) is not int or not 0 < amount <= MAX_AMOUNT:
        raise ShardError('給予數量必須為正整數。')
    with db.transaction(immediate=True) as tx:
        ensure_schema(tx)
        previous = tx.select('star_shard_request', {'userId': sender, 'requestId': request_id})
        if previous:
            if (previous[0]['recipientId'], previous[0]['amount']) != (recipient, amount):
                raise ShardError('此操作已使用，請重新開啟給予視窗。')
            return {'balance': balance(tx, sender), 'recordId': previous[0]['debitId']}
        debit = append_entry(tx, sender, -amount, 'transaction', recipient, '給予成員星之碎片')
        credit = append_entry(tx, recipient, amount, 'transaction', sender, '收到成員給予的星之碎片')
        tx.insert('star_shard_request', {'userId': sender, 'requestId': request_id,
            'recipientId': recipient, 'amount': amount, 'debitId': debit, 'creditId': credit})
        return {'balance': balance(tx, sender), 'recordId': debit}
