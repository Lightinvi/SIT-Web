"""Authenticated prediction reads and CSRF-protected, live-authorized management."""
import secrets
import math
import sqlite3
import time
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request, session

from app.api.auth import current_user
from app.models.prediction import PredictionRepository
from app.models.star_shard import ShardError, balance
from app.services.discord import DiscordError
from app.services.roles import highest_role

prediction_bp = Blueprint('prediction', __name__)


@prediction_bp.before_request
def authenticate():
    """Resolve the caller server-side and require CSRF on every write.
    取得目前登入者，並對所有寫入驗證 CSRF。

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
    g.prediction_user = user
    if request.method == 'POST':
        expected = session.get('csrf', '')
        if not expected or not secrets.compare_digest(expected.encode(), request.headers.get('X-CSRF-Token', '').encode()):
            return jsonify(error='請求已失效，請重新登入。'), 403


@prediction_bp.after_request
def private_response(response):
    """Avoid caching private stakes, balances and CSRF tokens.
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


@prediction_bp.errorhandler(sqlite3.Error)
def storage_error(error):
    """Retain a retryable operation ID when storage cannot confirm a transaction.
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
    current_app.logger.exception('Prediction storage operation failed')
    return jsonify(error='暫時無法確認操作結果，請重試相同操作。'), 503


@prediction_bp.errorhandler(ShardError)
def validation_error(error):
    """Return a sanitized rejected-intent message without committing partial changes.
    回傳已拒絕操作的公開驗證錯誤訊息。

    Args:
        error: 已由 Flask 或上游捕捉的例外物件。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = validation_error(error=error)
    """
    return jsonify(error=str(error)), 400


@prediction_bp.errorhandler(PermissionError)
def forbidden(error):
    """Reject unauthorized management or sponsorship operations.
    回傳權限不足的錯誤回應。

    Args:
        error: 已由 Flask 或上游捕捉的例外物件。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = forbidden(error=error)
    """
    return jsonify(error=str(error)), 403


@prediction_bp.errorhandler(DiscordError)
def upstream_error(error):
    """Fail closed when live role verification is unavailable.
    在即時身份驗證失敗時回傳 Discord 服務錯誤。

    Args:
        error: 已由 Flask 或上游捕捉的例外物件。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = upstream_error(error=error)
    """
    return jsonify(error=str(error)), error.status


def live_role():
    """Verify a live guild member; stored roles only control optional frontend hints.
    以 Bot 即時取得群組成員身份組，不以儲存的權限授予管理能力。

    Args:
        None: 無需傳入參數。

    Returns:
        str | None: 即時最高身份 key，無有效身份時為 None。

    Exceptions:
        DiscordError: Discord 存取、回應格式或快取服務無法完成操作。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = live_role()
    """
    service = current_app.extensions['discord']
    if not service.token:
        raise DiscordError('尚未設定 Discord Bot，無法驗證管理權限。', 503)
    member = service._request('members/' + g.prediction_user['id'])
    role = highest_role(member.get('roles'))
    if member.get('user', {}).get('id') != g.prediction_user['id'] or member.get('pending') or not role:
        return None
    return role['key']


@prediction_bp.get('/permissions')
def permissions():
    """Resolve live capabilities without granting authority based on the browser.
    回傳目前即時驗證的預測盤管理及贊助權限。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/predictions/permissions')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    role = live_role()
    return jsonify(canManage=role in ('admin', 'web_admin'), canSponsor=role == 'web_admin')


@prediction_bp.get('')
def markets():
    """List twenty markets at a time with current odds and the caller's own stakes.
    先依名稱、日期與狀態篩選，再回傳二十筆預測盤及本人押注資料。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Exceptions:
        ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
        ValueError: 已在函式內捕捉，轉成回應或替代結果。
        ValueError, TypeError: 已在函式內捕捉，轉成回應或替代結果。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/predictions')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    try:
        offset = int(request.args.get('offset', '0'))
        if not 0 <= offset <= 1_000_000:
            raise ValueError()
    except ValueError:
        return jsonify(error='無效的分頁。'), 400
    status = request.args.get('status', 'all')
    if status not in ('all', 'open', 'closed', 'finished'):
        return jsonify(error='無效的狀態。'), 400
    query = request.args.get('q', '').strip()[:120]
    now = time.time()
    where = "instr(lower(name), lower(?)) > 0"
    args = [query]
    start = request.args.get('closesFrom')
    end = request.args.get('closesBefore')
    if start is not None or end is not None:
        try:
            start, end = float(start), float(end)
            if not (math.isfinite(start) and math.isfinite(end) and 0 < start < end < 253402300800):
                raise ValueError()
        except (ValueError, TypeError):
            return jsonify(error='無效的日期範圍。'), 400
        where += ' AND closesAt>=? AND closesAt<?'
        args.extend((start, end))
    if status == 'open':
        where += " AND status='active' AND closesAt>?"; args.append(now)
    elif status == 'closed':
        where += " AND status='active' AND closesAt<=?"; args.append(now)
    elif status == 'finished':
        where += " AND status!='active'"
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        repository = PredictionRepository(tx)
        repository.ensure_schema()
        rows = tx.query(f'SELECT * FROM prediction_market WHERE {where} ORDER BY createdAt DESC, rowid DESC LIMIT 21 OFFSET ?', (*args, offset))
        result = [repository.market_view(market, g.prediction_user['id'], now) for market in rows[:20]]
        funds = balance(tx, g.prediction_user['id'])
    return jsonify(markets=result, nextOffset=offset+20 if len(rows)>20 else None, balance=funds,
                   userId=g.prediction_user['id'], csrfToken=session.get('csrf', ''), serverTime=now)


@prediction_bp.get('/<market_id>')
def detail(market_id):
    """Load fresh market metadata, odds and caller-owned stake totals.
    回傳指定預測盤最新內容、本人押注、餘額與 CSRF 權杖。

    Args:
        market_id: 預測盤 UUID；建立操作可使用 None。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get(f'/api/predictions/{market_id}')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        repository = PredictionRepository(tx)
        repository.ensure_schema()
        market = repository.market_view(repository.get_market(market_id), g.prediction_user['id'], time.time())
        funds = balance(tx, g.prediction_user['id'])
    return jsonify(market=market, balance=funds, userId=g.prediction_user['id'], csrfToken=session.get('csrf', ''))


@prediction_bp.post('')
@prediction_bp.post('/<market_id>/<action>')
def command(market_id=None, action='create'):
    """Authorize privileged commands live, then atomically execute a unique intention.
    驗證操作 UUID，對管理操作即時驗證身份，再執行原子預測盤操作。

    Args:
        market_id: 預測盤 UUID；建立操作可使用 None。 預設為 None。
        action: 要執行的操作名稱。 預設為 'create'。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Exceptions:
        ShardError: 金額、餘額、成員、狀態版本或操作內容不符合業務限制。 若由下列處理流程捕捉，則依其轉換規則處理。
        ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
        ValueError, TypeError, AttributeError: 捕捉後轉換為上列業務或驗證例外。

    Example:
        >>> client = app.test_client()
        >>> response = client.post('/api/predictions', json=payload, headers=headers)
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    if action not in ('create', 'edit', 'bet', 'settle', 'cancel') or (action == 'create' and market_id is not None):
        raise ShardError('無效的操作。')
    payload = request.get_json(silent=True)
    try:
        if not isinstance(payload, dict):
            raise ValueError()
        request_id = str(UUID(payload.get('requestId', '')))
    except (ValueError, TypeError, AttributeError):
        raise ShardError('無效的操作識別碼。') from None
    data = {key: value for key, value in payload.items() if key != 'requestId'}
    role = live_role() if action != 'bet' else None
    market = current_app.extensions['services'].predictions.execute(g.prediction_user['id'], request_id, action,
                     data, market_id=market_id, role=role)
    return jsonify(market=market)
