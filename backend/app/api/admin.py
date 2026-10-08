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
from app.models.star_shard import ShardError

admin_bp = Blueprint('admin', __name__)


@admin_bp.after_request
def private_response(response):
    """Prevent browser and proxy caches from retaining administration responses.
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


@admin_bp.before_request
def authorize():
    """Require a session, CSRF for writes, and a live web-admin Discord role.
    檢查登入、寫入 CSRF 與即時 Discord 網頁管理員身份。

    Args:
        None: 無需傳入參數。

    Returns:
        None | tuple[Response, int]: 驗證通過時繼續請求；失敗時回傳錯誤與狀態碼。

    Exceptions:
        DiscordError: 已在函式內捕捉，轉成回應或替代結果。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = authorize()
    """
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
    """Search registered recipients, including the administrator's own member record.
    搜尋最多五十位已登記的發放對象，包含管理員本人。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/admin/shards/members')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    query = request.args.get('q', '').strip()[:100]
    with current_app.extensions['sql'].transaction() as tx:
        rows = tx.query('''SELECT userId, username, displayName FROM member
            WHERE instr(lower(coalesce(username, '')), lower(?)) > 0
            OR instr(lower(coalesce(displayName, '')), lower(?)) > 0 OR userId = ?
            ORDER BY coalesce(displayName, username, userId), userId LIMIT 50''', (query, query, query))
    return jsonify(members=rows)


@admin_bp.post('/shards/grant')
def grant_shards():
    """Credit only after live administrator and CSRF checks; clients cannot choose the ledger type.
    驗證操作 UUID 後執行系統發放，回傳可追蹤管理員的憑證。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Exceptions:
        ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
        ValueError, TypeError, AttributeError: 已在函式內捕捉，轉成回應或替代結果。
        ShardError: 已在函式內捕捉，轉成回應或替代結果。
        sqlite3.Error: 已在函式內捕捉，轉成回應或替代結果。

    Example:
        >>> client = app.test_client()
        >>> response = client.post('/api/admin/shards/grant', json=payload, headers=headers)
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    payload = request.get_json(silent=True)
    try:
        if not isinstance(payload, dict):
            raise ValueError()
        request_id = str(UUID(payload.get('requestId', '')))
    except (ValueError, TypeError, AttributeError):
        return jsonify(error='無效的操作識別碼。'), 400
    try:
        receipt = current_app.extensions['services'].grants.grant(g.admin_user_id,
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
    """Confirm live authorization without exposing cached member information.
    確認網頁管理員已通過即時驗證。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/admin/status')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    return jsonify(authorized=True)


@admin_bp.get('/database')
def tables():
    """List existing user tables after live web-administrator authorization.
    在網頁管理員驗證後回傳資料表名稱清單。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/admin/database')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    return jsonify(tables=current_app.extensions['sql'].list_tables())


@admin_bp.get('/database/<table>')
def table_rows(table):
    """Expose a read-only page with validated sorting and a fixed 100-row limit.
    依驗證過的搜尋、排序及分頁參數回傳資料表內容。

    Args:
        table: 資料表名稱。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Exceptions:
        ValueError, OverflowError: 已在函式內捕捉，轉成回應或替代結果。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/admin/database/member')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    try:
        result = current_app.extensions['services'].database.table_page(table, request.args.get('sort'),
                            request.args.get('direction', 'asc'), int(request.args.get('offset', '0')),
                            request.args.get('q', ''), request.args.get('column'))
        return jsonify(result)
    except (ValueError, OverflowError):
        return jsonify(error='資料表、排序或分頁參數無效。'), 400


@admin_bp.get('/log')
def logs():
    """Return application JSON logs without exposing file-system paths.
    回傳日誌快照頁面，將無效游標與已輪替的快照轉成對應錯誤。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Exceptions:
        ValueError: 已在函式內捕捉，轉成回應或替代結果。
        LookupError: 已在函式內捕捉，轉成回應或替代結果。
        OSError: 已在函式內捕捉，轉成回應或替代結果。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/admin/log')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    try:
        return jsonify(current_app.extensions['services'].logs.log_page(request.args.get('cursor')))
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
    更新 Discord 快取與既有成員權限，撤銷失去資格的登入，保留歷史成員資料。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Exceptions:
        DiscordError: Discord 存取、回應格式或快取服務無法完成操作。 若由下列處理流程捕捉，則依其轉換規則處理。
        DiscordError: 已在函式內捕捉，轉成回應或替代結果。

    Example:
        >>> client = app.test_client()
        >>> response = client.post('/api/admin/sync', json=payload, headers=headers)
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
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
