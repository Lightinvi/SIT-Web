"""Authenticated and CSRF-protected blackjack commands; the server owns all cards."""
import secrets
import sqlite3
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request, session

from app.api.auth import current_user
from app.models.blackjack import BlackjackShoe, BlackjackRepository
from app.models.star_shard import ShardError

blackjack_bp = Blueprint('blackjack', __name__)


@blackjack_bp.after_request
def private_response(response):
    """Keep private hands and session tokens out of HTTP caches.
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


@blackjack_bp.errorhandler(sqlite3.Error)
def storage_error(error):
    """Report retryable storage errors without exposing game internals.
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
    current_app.logger.exception('Blackjack storage operation failed')
    return jsonify(error='暫時無法完成操作，請重試以確認結果。'), 503


@blackjack_bp.get('')
def status():
    """Restore the requesting member's last or active round without drawing cards.
    回傳登入成員最新或進行中的牌局，不抽牌或扣款。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/blackjack')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    user = current_user()
    if user is None:
        return jsonify(error='請先登入帳號。'), 401
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        BlackjackShoe(tx).ensure_schema()
        result = BlackjackRepository(tx).public_state(user['id'])
    return jsonify(**result, userId=user['id'], csrfToken=session.get('csrf', ''))


@blackjack_bp.post('')
def command():
    """Accept idempotent user intentions, never balances, cards or outcome claims.
    驗證登入、CSRF、動作與 UUID 後執行牌局操作，牌面及結果由伺服器決定。

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
        >>> response = client.post('/api/blackjack', json=payload, headers=headers)
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    user = current_user()
    if user is None:
        return jsonify(error='請先登入帳號。'), 401
    expected = session.get('csrf', '')
    if not expected or not secrets.compare_digest(expected.encode(), request.headers.get('X-CSRF-Token', '').encode()):
        return jsonify(error='請求已失效，請重新登入。'), 403
    payload = request.get_json(silent=True)
    try:
        if not isinstance(payload, dict):
            raise ValueError()
        request_id = str(UUID(payload.get('requestId', '')))
        if payload.get('action') not in ('start', 'hit', 'stand', 'double', 'split', 'insurance', 'decline'):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        return jsonify(error='無效的遊戲操作。'), 400
    try:
        result = current_app.extensions['services'].blackjack.play(user['id'], request_id, payload['action'],
                      bet=payload.get('bet'), round_id=payload.get('roundId'), version=payload.get('version'))
    except ShardError as error:
        return jsonify(error=str(error)), 400
    return jsonify(**result, userId=user['id'], csrfToken=expected)
