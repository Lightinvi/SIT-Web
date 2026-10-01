"""Live-authorized administration of Discord caches and stored member permissions."""
import json
import secrets
import time
import sqlite3
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request, session

from app.api.auth import current_user, database
from app.models.member import ensure_member_schema
from app.services.discord import DiscordError
from app.services.roles import highest_role
from app.services.admin_reader import table_page, log_page
from app.models.shard_grant import grant
from app.models.star_shard import ShardError

admin_bp = Blueprint('admin', __name__)


@admin_bp.after_request
def private_response(response):
    """Prevent browser and proxy caches from retaining administration responses."""
    response.headers['Cache-Control'] = 'no-store'
    return response


@admin_bp.before_request
def authorize():
    """Require a session, CSRF for writes, and a live web-admin Discord role."""
    user = current_user()
    if user is None:
        return jsonify(error='請先登入帳號。'), 401
    if request.method == 'POST':
        expected = session.get('csrf')
        if not expected or not secrets.compare_digest(expected, request.headers.get('X-CSRF-Token', '')):
            return jsonify(error='無效的操作請求。'), 403
    service = current_app.extensions['discord']
    if not service.token:
        return jsonify(error='尚未設定 DISCORD_BOT_TOKEN。'), 503
    try:
        member = service._request('members/' + user['id'])
    except DiscordError as error:
        return jsonify(error=str(error)), error.status
    role = highest_role(member.get('roles'))
    if member.get('user', {}).get('id') != user['id'] or member.get('pending') or not role or role['key'] != 'web_admin':
        return jsonify(error='僅限網頁管理員使用。'), 403
    g.admin_user_id = user['id']


@admin_bp.get('/shards/members')
def grant_members():
    """Search registered recipients, including the administrator's own member record."""
    query = request.args.get('q', '').strip()[:100]
    with current_app.extensions['sql'].transaction() as tx:
        rows = tx.query('''SELECT userId, username, displayName FROM member
            WHERE instr(lower(coalesce(username, '')), lower(?)) > 0
            OR instr(lower(coalesce(displayName, '')), lower(?)) > 0 OR userId = ?
            ORDER BY coalesce(displayName, username, userId), userId LIMIT 50''', (query, query, query))
    return jsonify(members=rows)


@admin_bp.post('/shards/grant')
def grant_shards():
    """Credit only after live administrator and CSRF checks; clients cannot choose the ledger type."""
    payload = request.get_json(silent=True)
    try:
        if not isinstance(payload, dict):
            raise ValueError()
        request_id = str(UUID(payload.get('requestId', '')))
    except (ValueError, TypeError, AttributeError):
        return jsonify(error='無效的操作識別碼。'), 400
    try:
        receipt = grant(current_app.extensions['sql'], g.admin_user_id,
                        payload.get('recipientId'), payload.get('amount'), request_id)
    except ShardError as error:
        return jsonify(error=str(error)), 400
    except sqlite3.Error:
        current_app.logger.exception('System shard grant failed')
        return jsonify(error='暫時無法確認發放結果，請重試相同操作。'), 503
    current_app.logger.info('System shard grant confirmed: grant=%s administrator=%s', receipt['id'], g.admin_user_id)
    return jsonify(receipt=receipt)


@admin_bp.get('/status')
def status():
    """Confirm live authorization without exposing cached member information."""
    return jsonify(authorized=True)


@admin_bp.get('/database')
def tables():
    """List existing user tables after live web-administrator authorization."""
    return jsonify(tables=current_app.extensions['sql'].list_tables())


@admin_bp.get('/database/<table>')
def table_rows(table):
    """Expose a read-only page with validated sorting and a fixed 100-row limit."""
    try:
        result = table_page(current_app.extensions['sql'], table, request.args.get('sort'),
                            request.args.get('direction', 'asc'), int(request.args.get('offset', '0')),
                            request.args.get('q', ''), request.args.get('column'))
        return jsonify(result)
    except (ValueError, OverflowError):
        return jsonify(error='資料表、排序或分頁參數無效。'), 400


@admin_bp.get('/log')
def logs():
    """Return application JSON logs without exposing file-system paths."""
    try:
        return jsonify(log_page(current_app.config['LOG_DIRECTORY'], current_app.secret_key,
                                request.args.get('cursor')))
    except ValueError:
        return jsonify(error='分頁參數無效，請重新整理。'), 400
    except LookupError:
        return jsonify(error='紀錄已輪替，請重新整理。'), 409
    except OSError:
        return jsonify(error='暫時無法讀取後端紀錄。'), 503


@admin_bp.post('/sync')
def sync():
    """Refresh both caches, then atomically update existing members and revoke lost access.

    Never register new website members from the guild list. Retain historical
    profiles for departed members, clearing only roles and their login sessions.
    """
    service = current_app.extensions['discord']
    try:
        roles = service.get('roles', force=True)
        result = service.get('members', force=True)
        members = {}
        for member in result['members']:
            user_id = member.get('user', {}).get('id')
            role_ids = member.get('roles')
            if (not isinstance(user_id, str) or not isinstance(role_ids, list)
                    or not all(isinstance(role, str) for role in role_ids) or user_id in members):
                raise DiscordError('Discord 成員資料不完整，未更新網站權限。')
            members[user_id] = member
    except DiscordError as error:
        return jsonify(error=str(error)), error.status
    db = database()
    updated = revoked = 0
    now = time.time()
    with db.transaction(immediate=True) as tx:
        ensure_member_schema(tx)
        for saved in tx.select('member'):
            member = members.get(saved['userId'])
            role_ids = member['roles'] if member and not member.get('pending') else []
            tx.update('member', {'roleIds': json.dumps(role_ids), 'rolesUpdatedAt': now}, {'userId': saved['userId']})
            updated += 1
            if highest_role(role_ids) is None:
                revoked += tx.delete('login_sessions', {'userId': saved['userId']})
    current_app.logger.info('Administrator synchronized Discord permissions: members=%s revoked_sessions=%s', updated, revoked)
    return jsonify(updatedMembers=updated, revokedSessions=revoked,
                   roleCount=len(roles['roles']), memberCount=len(members), updatedAt=now)
