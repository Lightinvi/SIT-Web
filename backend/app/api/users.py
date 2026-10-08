"""Expose the demo user collection separately from authenticated member profiles."""
from flask import Blueprint, jsonify
from app.services.users import get_users

users_bp = Blueprint("users", __name__)


@users_bp.get("", strict_slashes=False)
def list_users():
    """Return the static demo users as a JSON collection; no database is queried.
    回傳示範用戶列表的 JSON 回應。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/users')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    return jsonify(users=get_users())
