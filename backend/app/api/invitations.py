"""Serve dynamic join options and validate attributed invitation clicks."""
import secrets
import sqlite3
import uuid

from flask import Blueprint, current_app, jsonify, request, session

from app.models.invitation import ROLES, InvitationError, INVITATIONS
from app.services.discord import DiscordError

invitations_bp = Blueprint('invitations', __name__)


@invitations_bp.after_request
def no_cache(response):
    """Keep invitation settings, CSRF tokens, and validation responses out of caches.
    將邀請回應設定為不可快取。

    Args:
        response: Flask 即將送出的回應物件。

    Returns:
        Response: 加上回應標頭後的原回應物件。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = no_cache(response=response)
    """
    response.headers['Cache-Control'] = 'no-store'
    return response


@invitations_bp.errorhandler(InvitationError)
def invalid_invitation(error):
    """Return an actionable validation error without disclosing a protected invite code.
    將邀請驗證錯誤轉為公開 JSON 錯誤回應。

    Args:
        error: 已由 Flask 或上游捕捉的例外物件。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = invalid_invitation(error=error)
    """
    return jsonify(error=str(error)), error.status


@invitations_bp.errorhandler(DiscordError)
def discord_failure(error):
    """Return sanitized upstream errors with retry guidance.
    將 Discord 上游錯誤轉為帶有重試等待時間的回應。

    Args:
        error: 已由 Flask 或上游捕捉的例外物件。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = discord_failure(error=error)
    """
    response = jsonify(error=str(error))
    response.status_code = error.status
    response.headers['Retry-After'] = str(error.retry_after)
    return response


@invitations_bp.errorhandler(sqlite3.Error)
def database_failure(error):
    """Prevent redirects when recording fails and leave diagnostic details in server logs.
    記錄儲存錯誤並回傳邀請服務暫時不可用。

    Args:
        error: 已由 Flask 或上游捕捉的例外物件。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = database_failure(error=error)
    """
    current_app.logger.exception('Invitation database operation failed')
    return jsonify(error='邀請服務暫時無法使用，請稍後再試。'), 503


@invitations_bp.get('')
def list_invitations():
    """List role descriptions and disabled states without exposing invite URLs.
    初始化匿名訪客與 CSRF 識別碼，回傳邀請身份選項而不公開網址。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/invitations')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    if not current_app.secret_key:
        return jsonify(error='邀請服務尚未設定完成，請稍後再試。'), 503
    db = current_app.extensions['sql']
    current_app.extensions['services'].invitations.ensure_schema()
    if 'invitation_csrf' not in session:
        session['invitation_csrf'] = secrets.token_urlsafe(32)
    if 'invitation_visitor' not in session:
        session['invitation_visitor'] = secrets.token_urlsafe(24)
    return jsonify(invitations=[{
        'role': role, 'description': INVITATIONS[role]['description'],
        'isExpired': not bool(current_app.extensions['discord'].token), 'requiresCode': role == ROLES[2],
    } for role in ROLES], csrf_token=session['invitation_csrf'])


@invitations_bp.post('/click')
def click_invitation():
    """Validate a same-browser click, resolve the referrer, commit a record, and return a URL.
    驗證點擊及推薦人代碼，儲存邀請紀錄後回傳 Discord 邀請網址。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Exceptions:
        InvitationError: 邀請方式、歸屬、期限或服务設定不符合要求。 若由下列處理流程捕捉，則依其轉換規則處理。
        ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
        ValueError: 捕捉後轉換為上列業務或驗證例外。
        DiscordError: 已在函式內捕捉，轉成回應或替代結果。

    Example:
        >>> client = app.test_client()
        >>> response = client.post('/api/invitations/click', json=payload, headers=headers)
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    expected = session.get('invitation_csrf')
    if (not expected or not session.get('invitation_visitor')
            or not secrets.compare_digest(expected, request.headers.get('X-CSRF-Token', ''))):
        return jsonify(error='此視窗已失效，請關閉後重新開啟。'), 403
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get('role') not in ROLES:
        raise InvitationError('請選擇有效的加入方式。')
    request_id = payload.get('request_id')
    try:
        if not isinstance(request_id, str) or str(uuid.UUID(request_id)) != request_id:
            raise ValueError
    except ValueError:
        raise InvitationError('點擊識別碼無效，請重試。') from None
    role = payload['role']
    db = current_app.extensions['sql']
    current_app.extensions['services'].invitations.ensure_schema()
    administrator = None
    if role == ROLES[2]:
        username = payload.get('administrator_code')
        if not isinstance(username, str) or not username.strip() or len(username) > 64:
            raise InvitationError('請輸入管理員派發的代碼。')
        try:
            administrator = current_app.extensions['discord'].find_administrator(
                username.strip(), current_app.config['DISCORD_ADMIN_ROLE_IDS'])
        except DiscordError as error:
            return jsonify(error='目前無法驗證代碼，請稍後再試。'), error.status
        if administrator is None:
            raise InvitationError('找不到此代碼，請確認後再試。')
    record = current_app.extensions['services'].invitations.record_click(role, session['invitation_visitor'], request_id, administrator, discord=current_app.extensions['discord'])
    return jsonify(record_id=record['id'], url=f"https://discord.com/invite/{record['code']}")
