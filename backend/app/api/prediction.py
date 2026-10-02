"""Authenticated prediction reads and CSRF-protected, live-authorized management."""
import secrets
import math
import sqlite3
import time
from uuid import UUID

from flask import Blueprint, current_app, g, jsonify, request, session

from app.api.auth import current_user
from app.models.prediction import ensure_schema, execute, get_market, market_view
from app.models.star_shard import ShardError, balance
from app.services.discord import DiscordError
from app.services.roles import highest_role

prediction_bp = Blueprint('prediction', __name__)


@prediction_bp.before_request
def authenticate():
    """Resolve the caller server-side and require CSRF on every write."""
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
    """Avoid caching private stakes, balances and CSRF tokens."""
    response.headers['Cache-Control'] = 'no-store'
    return response


@prediction_bp.errorhandler(sqlite3.Error)
def storage_error(error):
    """Retain a retryable operation ID when storage cannot confirm a transaction."""
    current_app.logger.exception('Prediction storage operation failed')
    return jsonify(error='暫時無法確認操作結果，請重試相同操作。'), 503


@prediction_bp.errorhandler(ShardError)
def validation_error(error):
    """Return a sanitized rejected-intent message without committing partial changes."""
    return jsonify(error=str(error)), 400


@prediction_bp.errorhandler(PermissionError)
def forbidden(error):
    """Reject unauthorized management or sponsorship operations."""
    return jsonify(error=str(error)), 403


@prediction_bp.errorhandler(DiscordError)
def upstream_error(error):
    """Fail closed when live role verification is unavailable."""
    return jsonify(error=str(error)), error.status


def live_role():
    """Verify a live guild member; stored roles only control optional frontend hints."""
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
    """Resolve live capabilities without granting authority based on the browser."""
    role = live_role()
    return jsonify(canManage=role in ('admin', 'web_admin'), canSponsor=role == 'web_admin')


@prediction_bp.get('')
def markets():
    """List twenty markets at a time with current odds and the caller's own stakes."""
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
        ensure_schema(tx)
        rows = tx.query(f'SELECT * FROM prediction_market WHERE {where} ORDER BY createdAt DESC, rowid DESC LIMIT 21 OFFSET ?', (*args, offset))
        result = [market_view(tx, market, g.prediction_user['id'], now) for market in rows[:20]]
        funds = balance(tx, g.prediction_user['id'])
    return jsonify(markets=result, nextOffset=offset+20 if len(rows)>20 else None, balance=funds,
                   userId=g.prediction_user['id'], csrfToken=session.get('csrf', ''), serverTime=now)


@prediction_bp.get('/<market_id>')
def detail(market_id):
    """Load fresh market metadata, odds and caller-owned stake totals."""
    with current_app.extensions['sql'].transaction(immediate=True) as tx:
        ensure_schema(tx)
        market = market_view(tx, get_market(tx, market_id), g.prediction_user['id'], time.time())
        funds = balance(tx, g.prediction_user['id'])
    return jsonify(market=market, balance=funds, userId=g.prediction_user['id'], csrfToken=session.get('csrf', ''))


@prediction_bp.post('')
@prediction_bp.post('/<market_id>/<action>')
def command(market_id=None, action='create'):
    """Authorize privileged commands live, then atomically execute a unique intention."""
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
    market = execute(current_app.extensions['sql'], g.prediction_user['id'], request_id, action,
                     data, market_id=market_id, role=role)
    return jsonify(market=market)
