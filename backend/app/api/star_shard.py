"""Authenticated balance, cursor history, member lookup, and CSRF-protected transfers."""
import secrets
import sqlite3
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request, session

from app.api.auth import current_user
from app.models.star_shard import ShardError, ShardLedger

shards_bp = Blueprint('star_shard', __name__)


@shards_bp.before_request
def authenticate():
    """Resolve identity exclusively from the valid server-side login session.
    依有效登入 session 取得轉讓者身份，未登入時拒絕請求。

    Args:
        None: 無需傳入參數。

    Returns:
        None | tuple[Response, int]: 驗證通過時繼續請求；失敗時回傳錯誤與狀態碼。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = authenticate()
    """
    user = current_user()
    if user is None:
        return jsonify(error='請先登入帳號。'), 401
    g.shard_user = user['id']


@shards_bp.after_request
def private_response(response):
    """Prevent private balances and recipient lists from being cached.
    為回應加上禁止快取標頭，以保護私人資料。

    Args:
        response: Flask 即將送出的回應物件。

    Returns:
        Response: 加上回應標頭後的原回應物件。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = private_response(response=response)
    """
    response.headers['Cache-Control'] = 'no-store'
    return response


@shards_bp.errorhandler(sqlite3.Error)
def storage_error(error):
    """Hide storage internals and allow clients to retry with the same request ID.
    記錄資料庫失敗並回傳可重試的服務錯誤。

    Args:
        error: 已由 Flask 或上游捕捉的例外物件。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = storage_error(error=error)
    """
    current_app.logger.exception(
        'Star Shard database operation failed: %s',
        error
    )
    return jsonify(error='暫時無法處理，請稍後重試。'), 503


@shards_bp.get('/balance')
def get_balance():
    """Return the current member's latest balance or zero when no entries exist.
    回傳目前登入成員的最新碎片餘額。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/star-shards/balance')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        ledger = ShardLedger(tx)
        ledger.ensure_schema()
        return jsonify(balance=ledger.balance(g.shard_user))


@shards_bp.get('/records')
def records():
    """Resolve an own UUID cursor to its ledger sequence and return twenty entries.
    將本人 UUID 游標解析成帳本序號，回傳最多二十筆私人交易紀錄。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Exceptions:
        ValueError: 已在函式內捕捉，轉成回應或替代結果。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/star-shards/records')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    cursor = request.args.get('before')
    if cursor is not None:
        try:
            cursor = str(UUID(cursor))
        except ValueError:
            return jsonify(error='無效的紀錄游標。'), 400
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        ShardLedger(tx).ensure_schema()
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
    """Search up to fifty stored members, excluding the authenticated sender.
    搜尋已登記成員，排除目前登入的轉出者。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/star-shards/members')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    query = request.args.get('q', '').strip()[:100]
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        ShardLedger(tx).ensure_schema()
        rows = tx.query('''SELECT userId, username, displayName FROM member
            WHERE userId != ? AND (instr(lower(coalesce(username, '')), lower(?)) > 0
            OR instr(lower(coalesce(displayName, '')), lower(?)) > 0 OR userId = ?)
            ORDER BY coalesce(displayName, username, userId), userId LIMIT 50''',
            (g.shard_user, query, query, query))
        return jsonify(members=rows)


@shards_bp.post('/transfer')
def give():
    """Validate CSRF and an idempotency UUID before executing a server-owned transfer.
    驗證 CSRF 與操作 UUID 後執行碎片轉讓。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Exceptions:
        ValueError, TypeError, AttributeError: 已在函式內捕捉，轉成回應或替代結果。
        ShardError: 已在函式內捕捉，轉成回應或替代結果。

    Example:
        >>> client = app.test_client()
        >>> response = client.post('/api/star-shards/transfer', json=payload, headers=headers)
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
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
        result = current_app.extensions['services'].shards.transfer(g.shard_user,
            data.get('recipientId'), data.get('amount'), request_id)
    except ShardError as error:
        return jsonify(error=str(error)), 400
    return jsonify(result)
