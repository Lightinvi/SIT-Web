"""Authenticated and CSRF-protected blackjack commands; the server owns all cards."""
import secrets
import sqlite3
from uuid import UUID

from flask import Blueprint, current_app, jsonify, request, session

from app.api.auth import current_user
from app.models.blackjack import ensure_schema, play, public_state
from app.models.star_shard import ShardError

blackjack_bp = Blueprint('blackjack', __name__)


@blackjack_bp.after_request
def private_response(response):
    """Keep private hands and session tokens out of HTTP caches."""
    response.headers['Cache-Control'] = 'no-store'
    return response


@blackjack_bp.errorhandler(sqlite3.Error)
def storage_error(error):
    """Report retryable storage errors without exposing game internals."""
    current_app.logger.exception('Blackjack storage operation failed')
    return jsonify(error='暫時無法完成操作，請重試以確認結果。'), 503


@blackjack_bp.get('')
def status():
    """Restore the requesting member's last or active round without drawing cards."""
    user = current_user()
    if user is None:
        return jsonify(error='請先登入帳號。'), 401
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        ensure_schema(tx)
        result = public_state(tx, user['id'])
    return jsonify(**result, userId=user['id'], csrfToken=session.get('csrf', ''))


@blackjack_bp.post('')
def command():
    """Accept idempotent user intentions, never balances, cards or outcome claims."""
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
        result = play(current_app.extensions['sql'], user['id'], request_id, payload['action'],
                      bet=payload.get('bet'), round_id=payload.get('roundId'), version=payload.get('version'))
    except ShardError as error:
        return jsonify(error=str(error)), 400
    return jsonify(**result, userId=user['id'], csrfToken=expected)
