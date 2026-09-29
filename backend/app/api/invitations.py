"""Serve database-driven join options and validate attributed invitation clicks."""
import secrets
import sqlite3
import uuid

from flask import Blueprint, current_app, jsonify, request, session

from app.models.invitation import ROLES, InvitationError, ensure_schema, get_invitation, record_click
from app.services.discord import DiscordError

invitations_bp = Blueprint('invitations', __name__)


@invitations_bp.after_request
def no_cache(response):
    """Keep invitation settings, CSRF tokens, and validation responses out of caches."""
    response.headers['Cache-Control'] = 'no-store'
    return response


@invitations_bp.errorhandler(InvitationError)
def invalid_invitation(error):
    """Return an actionable validation error without disclosing a protected invite code."""
    return jsonify(error=str(error)), error.status


@invitations_bp.errorhandler(sqlite3.Error)
def database_failure(error):
    """Prevent redirects when recording fails and leave diagnostic details in server logs."""
    current_app.logger.exception('Invitation database operation failed')
    return jsonify(error='邀請服務暫時無法使用，請稍後再試。'), 503


@invitations_bp.get('')
def list_invitations():
    """List role descriptions and disabled states without exposing invite URLs."""
    if not current_app.secret_key:
        return jsonify(error='邀請服務尚未設定完成，請稍後再試。'), 503
    db = current_app.extensions['sql']
    ensure_schema(db)
    if 'invitation_csrf' not in session:
        session['invitation_csrf'] = secrets.token_urlsafe(32)
    if 'invitation_visitor' not in session:
        session['invitation_visitor'] = secrets.token_urlsafe(24)
    rows = {row['role']: row for row in db.select('invitation_url')}
    return jsonify(invitations=[{
        'role': role, 'description': rows[role]['description'],
        'isExpired': bool(rows[role]['isExpired']), 'requiresCode': role == ROLES[2],
    } for role in ROLES if role in rows], csrf_token=session['invitation_csrf'])


@invitations_bp.post('/click')
def click_invitation():
    """Validate a same-browser click, resolve the referrer, commit a record, and return a URL."""
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
    ensure_schema(db)
    get_invitation(db, role)
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
    record = record_click(db, role, session['invitation_visitor'], request_id, administrator)
    return jsonify(record_id=record['id'], url=f"https://discord.com/invite/{record['code']}")
