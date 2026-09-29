"""Authenticated balance, cursor history, member lookup, and CSRF-protected transfers."""
import secrets
import sqlite3
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request, session

from app.api.auth import current_user
from app.models.star_shard import ShardError, balance, ensure_schema, transfer

shards_bp = Blueprint('star_shard', __name__)


@shards_bp.before_request
def authenticate():
    """Resolve identity exclusively from the valid server-side login session."""
    user = current_user()
    if user is None:
        return jsonify(error='請先登入帳號。'), 401
    g.shard_user = user['id']


@shards_bp.after_request
def private_response(response):
    """Prevent private balances and recipient lists from being cached."""
    response.headers['Cache-Control'] = 'no-store'
    return response


@shards_bp.errorhandler(sqlite3.Error)
def storage_error(error):
    """Hide storage internals and allow clients to retry with the same request ID."""
    current_app.logger.exception('Star Shard database operation failed')
    return jsonify(error='暫時無法處理，請稍後重試。'), 503


@shards_bp.get('/balance')
def get_balance():
    """Return the current member's latest balance or zero when no entries exist."""
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        ensure_schema(tx)
        return jsonify(balance=balance(tx, g.shard_user))


@shards_bp.get('/records')
def records():
    """Resolve an own UUID cursor to its ledger sequence and return twenty entries."""
    cursor = request.args.get('before')
    if cursor is not None:
        try:
            cursor = str(UUID(cursor))
        except ValueError:
            return jsonify(error='無效的紀錄游標。'), 400
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        ensure_schema(tx)
        sequence = None
        if cursor is not None:
            previous = tx.select('star_shard', {'id': cursor, 'userId': g.shard_user})
            if not previous:
                return jsonify(error='無效的紀錄游標，請重新載入。'), 400
            sequence = previous[0]['sequence']
        rows = tx.query('SELECT * FROM star_shard WHERE userId=?' +
            (' AND sequence<?' if sequence is not None else '') + ' ORDER BY sequence DESC LIMIT 21',
            (g.shard_user, sequence) if sequence is not None else (g.shard_user,))
        for row in rows:
            row.pop('sequence')
        return jsonify(records=rows[:20], nextCursor=rows[19]['id'] if len(rows) > 20 else None)


@shards_bp.get('/members')
def members():
    """Search up to fifty stored members, excluding the authenticated sender."""
    query = request.args.get('q', '').strip()[:100]
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        ensure_schema(tx)
        rows = tx.query('''SELECT userId, username, displayName FROM member
            WHERE userId != ? AND (instr(lower(coalesce(username, '')), lower(?)) > 0
            OR instr(lower(coalesce(displayName, '')), lower(?)) > 0 OR userId = ?)
            ORDER BY coalesce(displayName, username, userId), userId LIMIT 50''',
            (g.shard_user, query, query, query))
        return jsonify(members=rows)


@shards_bp.post('/transfer')
def give():
    """Validate CSRF and an idempotency UUID before executing a server-owned transfer."""
    expected = session.get('csrf')
    if not expected or not secrets.compare_digest(expected, request.headers.get('X-CSRF-Token', '')):
        return jsonify(error='請求已失效，請重新登入。'), 403
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error='無效的請求。'), 400
    try:
        request_id = str(UUID(data.get('requestId', '')))
    except (ValueError, TypeError, AttributeError):
        return jsonify(error='無效的操作識別碼。'), 400
    try:
        result = transfer(current_app.extensions['sql'], g.shard_user,
            data.get('recipientId'), data.get('amount'), request_id)
    except ShardError as error:
        return jsonify(error=str(error)), 400
    return jsonify(result)
