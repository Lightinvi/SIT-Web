"""Public daily odds and authenticated, CSRF-protected daily spinner rewards."""
import secrets
import sqlite3
import time
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request, session

from app.api.auth import current_user
from app.models.daily_spinner import ensure_schema, member_state, public_state, spin
from app.models.star_shard import ShardError

spinner_bp = Blueprint('daily_spinner', __name__)


@spinner_bp.after_request
def private_response(response):
    """Never cache a member's eligibility, result, or CSRF token."""
    response.headers['Cache-Control'] = 'no-store'
    return response


@spinner_bp.errorhandler(sqlite3.Error)
def storage_error(error):
    """Allow a retry without revealing database internals or claiming a failed award."""
    current_app.logger.exception('Daily spinner database operation failed')
    return jsonify(error='暫時無法完成轉盤，請重試以確認結果。'), 503


@spinner_bp.get('')
def status():
    """Publish odds for everyone and include only the signed-in member's eligibility."""
    user = current_user()
    if user is None:
        return jsonify(**public_state(time.time()), authenticated=False, canSpin=False, todaySpin=None)
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        ensure_schema(tx)
        state = member_state(tx, user['id'], time.time())
    return jsonify(**state, authenticated=True, userId=user['id'], csrfToken=session.get('csrf', ''))


@spinner_bp.post('/spin')
def draw():
    """Ignore client-supplied prize or user fields and award only the current account."""
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
        result = spin(current_app.extensions['sql'], user['id'], request_id)
    except ShardError as error:
        return jsonify(error=str(error)), 400
    return jsonify(**result, authenticated=True, userId=user['id'], csrfToken=expected)
