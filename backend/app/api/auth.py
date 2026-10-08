"""Manage Discord OAuth, persistent member profiles, and server-side login sessions."""
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

from flask import Blueprint, current_app, jsonify, redirect, request, session

from app.services.oauth import OAuthError
from app.models.member import MemberProfileStore
from app.services.roles import highest_role


auth_bp = Blueprint('auth', __name__)


def database():
    """Return the app SQL manager after lazily creating OAuth and login-session tables.
    取得應用程式 SQL 管理器並初始化 OAuth 與登入資料表，必要時遷移舊登入資料。

    Args:
        None: 無需傳入參數。

    Returns:
        SQLManager: 目前應用程式的資料庫管理器。

    Exceptions:
        ValueError, KeyError, TypeError: 已在函式內捕捉，使用備援流程、略過無效資料或完成清理。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = database()
    """
    db = current_app.extensions['sql']
    db.execute('CREATE TABLE IF NOT EXISTS oauth_states (id TEXT PRIMARY KEY, expires REAL NOT NULL)')
    with db.transaction(immediate=True) as tx:
        MemberProfileStore(tx).ensure_member_schema()
        columns = {row['name'] for row in tx.query('PRAGMA table_info(login_sessions)')}
        if 'user' in columns:
            MemberProfileStore(tx).ensure_member_schema()
            rows = tx.query('SELECT * FROM login_sessions ORDER BY expires DESC')
            tx.execute('ALTER TABLE login_sessions RENAME TO legacy_login_sessions')
        else:
            rows = []
        tx.execute('''CREATE TABLE IF NOT EXISTS login_sessions (
            id TEXT PRIMARY KEY, userId TEXT NOT NULL REFERENCES member(userId) ON DELETE CASCADE,
            expires REAL NOT NULL)''')
        for row in rows:
            try:
                user = json.loads(row['user'])
                user_id = user['id']
            except (ValueError, KeyError, TypeError):
                continue
            members = tx.select('member', {'userId': user_id})
            if not members or row['expires'] <= time.time():
                continue
            if members[0]['roleIds'] is None and isinstance(user.get('role_ids'), list):
                tx.update('member', {'roleIds': json.dumps(user['role_ids'])}, {'userId': user_id})
            tx.insert('login_sessions', {'id': row['id'], 'userId': user_id, 'expires': row['expires']})
        if 'user' in columns:
            tx.execute('DROP TABLE legacy_login_sessions')
        tx.execute('CREATE INDEX IF NOT EXISTS login_sessions_userId ON login_sessions(userId)')
    return db


def digest(value):
    """Hash an opaque OAuth state or login identifier before storing or looking it up.
    將 OAuth state 或登入識別碼轉為 SHA-256 摘要以供儲存與查詢。

    Args:
        value: 待驗證或轉換的值。

    Returns:
        str: SHA-256 十六進位摘要。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = digest(value=value)
    """
    return hashlib.sha256(value.encode()).hexdigest()


def fail(code):
    """Redirect to the homepage with a URL-encoded authentication error code.
    記錄登入拒絕原因並導向帶有驗證錯誤碼的首頁。

    Args:
        code: 公開的登入錯誤碼。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = fail(code=code)
    """
    current_app.logger.warning('Discord login rejected: %s', code)
    return redirect('/?' + urlencode({'auth_error': code}))


@auth_bp.after_request
def private_response(response):
    """Prevent caching authentication responses and leaking callback URLs via referrers.
    禁止快取登入回應，並以 no-referrer 防止 callback 網址外洩。

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
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@auth_bp.get('/discord/login')
def login():
    """Start Discord authorization with a single-use state valid for ten minutes.

    Purge expired authentication records and keep the unhashed state in Flask's
    signed cookie so the callback must match both the cookie and database record.
    清理過期驗證紀錄，建立十分鐘有效且限用一次的 OAuth state 並導向 Discord。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/auth/discord/login')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    config = current_app.config
    if not all(config.get(key) for key in ('SECRET_KEY', 'DISCORD_CLIENT_ID', 'DISCORD_CLIENT_SECRET', 'DISCORD_REDIRECT_URI')):
        return fail('not_configured')
    state = secrets.token_urlsafe(32)
    db = database()
    with db.transaction() as tx:
        tx.execute('DELETE FROM oauth_states WHERE expires <= ?', (time.time(),))
        tx.execute('DELETE FROM login_sessions WHERE expires <= ?', (time.time(),))
        tx.insert('oauth_states', {'id': digest(state), 'expires': time.time() + 600})
    session['oauth_state'] = state
    return redirect('https://discord.com/oauth2/authorize?' + urlencode({
        'client_id': config['DISCORD_CLIENT_ID'], 'redirect_uri': config['DISCORD_REDIRECT_URI'],
        'response_type': 'code', 'scope': 'identify guilds.members.read', 'state': state,
    }))


@auth_bp.get('/discord/callback')
def callback():
    """Consume a valid OAuth state, verify guild membership, and establish a login.

    Store the member profile and login session in one transaction. Session expiry
    uses Flask's permanent_session_lifetime, defaulting to seven days from login.
    Discord access tokens are used only during verification and are not persisted.
    消耗有效 OAuth state，驗證群組身份並在同一交易內建立成員與登入紀錄。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Exceptions:
        OAuthError: 已在函式內捕捉，轉成回應或替代結果。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/auth/discord/callback')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    expected = session.pop('oauth_state', None)
    state = request.args.get('state', '')
    if not expected or not secrets.compare_digest(expected, state):
        return fail('invalid_state')
    db = database()
    with db.transaction() as tx:
        consumed = tx.execute('DELETE FROM oauth_states WHERE id=? AND expires>?',
                              (digest(state), time.time()))['rowcount']
    if consumed != 1:
        return fail('invalid_state')
    if request.args.get('error'):
        return fail('cancelled')
    code = request.args.get('code')
    if not code:
        return fail('invalid_state')
    # Remove an existing login before attempting a new identity.
    previous = session.get('login_id')
    if previous:
        db.delete('login_sessions', {'id': digest(previous)})
    session.clear()
    try:
        user = current_app.extensions['services'].oauth.authenticate(code)
    except OAuthError as error:
        return fail(str(error))
    login_id = secrets.token_urlsafe(32)
    logged_in_at = time.time()
    with db.transaction() as tx:
        MemberProfileStore(tx).record_login(user, logged_in_at)
        tx.insert('login_sessions', {'id': digest(login_id), 'userId': user['id'],
                                     'expires': logged_in_at + current_app.permanent_session_lifetime.total_seconds()})
    session['login_id'] = login_id
    session['csrf'] = secrets.token_urlsafe(32)
    session.permanent = True
    return redirect('/')


def current_user():
    """Resolve the session's userId against the authoritative member profile.

    Delete an expired database record and clear its browser session on access.
    Reading a valid session does not extend the stored database expiration.
    依登入 session 讀取權威成員資料，失效時清除登入，不延長資料庫到期時間。

    Args:
        None: 無需傳入參數。

    Returns:
        dict | None: 目前登入者資料及最高身份，失效時為 None。

    Example:
        由 Flask 在請求鉤子或錯誤處理流程中呼叫；直接呼叫須準備對應 request context。
        >>> with app.test_request_context():
        ...     result = current_user()
    """
    login_id = session.get('login_id')
    if not login_id:
        return None
    db = database()
    rows = db.select('login_sessions', {'id': digest(login_id)})
    if not rows or rows[0]['expires'] <= time.time():
        if rows:
            db.delete('login_sessions', {'id': digest(login_id)})
        session.clear()
        return None
    member = current_app.extensions['services'].members.get_member(rows[0]['userId'])
    if member is None:
        db.delete('login_sessions', {'id': digest(login_id)})
        session.clear()
        return None
    return {**member, 'id': member['user_id'],
            'name': member['display_name'] or member['username'],
            'access_role': highest_role(member['role_ids'])}


@auth_bp.get('/session')
def session_status():
    """Return authentication state and, for a valid login, the user and logout CSRF token.

    Prefer the saved member's display name and avatar over the login snapshot.
    回傳登入狀態，以及已登入使用者資料與登出 CSRF 權杖。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/auth/session')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    user = current_user()
    if user is None:
        return jsonify(authenticated=False)
    member = current_app.extensions['services'].members.get_member(user['id'])
    if member:
        user = {**user, 'name': member['display_name'] or member['username'],
                'avatar_url': member['avatar_url']}
    return jsonify(authenticated=True, user=user, csrf_token=session['csrf'])


@auth_bp.get('/profile')
def profile():
    """Return only the current user's saved profile; use 401 or 404 when unavailable.
    回傳目前登入者的個人資料，未登入或缺少紀錄時回報錯誤。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.get('/api/auth/profile')
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    user = current_user()
    if user is None:
        return jsonify(error='請先登入帳號。'), 401
    db = current_app.extensions['sql']
    member = current_app.extensions['services'].members.get_member(user['id'])
    if member is None:
        return jsonify(error='尚無個人資料，請登出後重新登入。'), 404
    return jsonify(member={**member, 'access_role': highest_role(user.get('role_ids'))})


@auth_bp.post('/logout')
def logout():
    """Invalidate the current login and cookie after validating the logout CSRF header.
    驗證 CSRF 後刪除登入紀錄並清除瀏覽器 session。

    Args:
        None: 無需傳入參數。

    Returns:
        Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

    Example:
        >>> client = app.test_client()
        >>> response = client.post('/api/auth/logout', json=payload, headers=headers)
        受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
    """
    expected = session.get('csrf')
    if not expected or not secrets.compare_digest(expected, request.headers.get('X-CSRF-Token', '')):
        return jsonify(error='無效的登出請求。'), 403
    if session.get('login_id'):
        database().delete('login_sessions', {'id': digest(session['login_id'])})
    session.clear()
    return jsonify(authenticated=False)
