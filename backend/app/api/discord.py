"""Serve cached Discord guild collections with sanitized errors and retry guidance."""
from flask import Blueprint, current_app, jsonify

from app.services.discord import DiscordError


discord_bp = Blueprint('discord', __name__)


def respond(resource):
    """Return a cached resource or a client-safe failure with Retry-After metadata.
    回傳 Discord 快取資料，失敗時提供公開錯誤與 Retry-After 標頭。

    Args:
        resource: Discord 資源名稱或群組內相對路徑。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Exceptions:
        DiscordError: 已在函式內捕捉，使用備援流程、略過無效資料或完成清理。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = respond(resource=resource)
    """
    try:
        response = jsonify(current_app.extensions['discord'].get(resource))
    except DiscordError as error:
        response = jsonify(error=str(error))
        response.status_code = error.status
        response.headers['Retry-After'] = str(error.retry_after)
    response.headers['Cache-Control'] = 'no-store'
    return response


@discord_bp.get('/members', strict_slashes=False)
def list_members():
    """Return the configured guild's member collection through the shared cache.
    透過共享快取回傳已設定群組的成員清單。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/discord/members')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    return respond('members')


@discord_bp.get('/roles', strict_slashes=False)
def list_roles():
    """Return the configured guild's role collection through the shared cache.
    透過共享快取回傳已設定群組的身份組清單。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/discord/roles')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    return respond('roles')
