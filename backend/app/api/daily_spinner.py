"""Public daily odds and authenticated, CSRF-protected daily spinner rewards."""
import secrets
import sqlite3
import time
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request, session

from app.api.auth import current_user
from app.models.daily_spinner import SpinnerRepository, public_state
from app.models.star_shard import ShardError

spinner_bp = Blueprint('daily_spinner', __name__)


@spinner_bp.after_request
def private_response(response):
    """Never cache a member's eligibility, result, or CSRF token.
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


@spinner_bp.errorhandler(sqlite3.Error)
def storage_error(error):
    """Allow a retry without revealing database internals or claiming a failed award.
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
    current_app.logger.exception('Daily spinner database operation failed')
    return jsonify(error='暫時無法完成轉盤，請重試以確認結果。'), 503


@spinner_bp.get('')
def status():
    """Publish odds for everyone and include only the signed-in member's eligibility.
    公開轉盤機率，已登入時附上本人當日資格與結果。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/daily-spinner')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    user = current_user()
    if user is None:
        return jsonify(**public_state(time.time()), authenticated=False, canSpin=False, todaySpin=None)
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        repository = SpinnerRepository(tx)
        repository.ensure_schema()
        state = repository.member_state(user['id'], time.time())
    return jsonify(**state, authenticated=True, userId=user['id'], csrfToken=session.get('csrf', ''))


@spinner_bp.post('/spin')
def draw():
    """Ignore client-supplied prize or user fields and award only the current account.
    只對目前登入者執行每日抽獎，忽略用戶端提供的獎勵或使用者欄位。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Exceptions:
        ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
        ValueError, TypeError, AttributeError: 已在函式內捕捉，轉成回應或替代結果。
        ShardError: 已在函式內捕捉，轉成回應或替代結果。

    Example:
        >>> client = app.test_client()
        >>> response = client.post('/api/daily-spinner/spin', json=payload, headers=headers)
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    user = current_user()
    if user is None:
        return jsonify(error='請先登入帳號。'), 401
    expected = session.get('csrf', '')
    supplied = request.headers.get('X-CSRF-Token', '')
    if not expected or not secrets.compare_digest(expected.encode(), supplied.encode()):
        return jsonify(error='請求已失效，請重新登入。'), 403
    payload = request.get_json(silent=True)
    try:
        request_id = str(UUID(payload.get('requestId', ''))) if isinstance(payload, dict) else ''
        if not request_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return jsonify(error='無效的操作識別碼。'), 400
    try:
        result = current_app.extensions['services'].spinner.spin(user['id'], request_id)
    except ShardError as error:
        return jsonify(error=str(error)), 400
    return jsonify(**result, authenticated=True, userId=user['id'], csrfToken=expected)
