import hashlib
import json
import secrets
import time
from urllib.parse import urlencode

from flask import Blueprint, current_app, jsonify, redirect, request, session

from app.services.oauth import OAuthError, authenticate
from app.models.member import get_member, record_login


auth_bp = Blueprint('auth', __name__)


def database():
    db = current_app.extensions['sql']
    db.execute('CREATE TABLE IF NOT EXISTS oauth_states (id TEXT PRIMARY KEY, expires REAL NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS login_sessions (id TEXT PRIMARY KEY, user TEXT NOT NULL, expires REAL NOT NULL)')
    return db


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def fail(code):
    return redirect('/?' + urlencode({'auth_error': code}))


@auth_bp.after_request
def private_response(response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


@auth_bp.get('/discord/login')
def login():
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
        user = authenticate(code, current_app.config)
    except OAuthError as error:
        return fail(str(error))
    login_id = secrets.token_urlsafe(32)
    logged_in_at = time.time()
    with db.transaction() as tx:
        record_login(tx, user, logged_in_at)
        tx.insert('login_sessions', {'id': digest(login_id), 'user': json.dumps(user),
                                     'expires': logged_in_at + 28800})
    session['login_id'] = login_id
    session['csrf'] = secrets.token_urlsafe(32)
    session.permanent = True
    return redirect('/')


def current_user():
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
    return json.loads(rows[0]['user'])


@auth_bp.get('/session')
def session_status():
    user = current_user()
    if user is None:
        return jsonify(authenticated=False)
    member = get_member(current_app.extensions['sql'], user['id'])
    if member:
        user = {**user, 'name': member['display_name'] or member['username'],
                'avatar_url': member['avatar_url']}
    return jsonify(authenticated=True, user=user, csrf_token=session['csrf'])


@auth_bp.get('/profile')
def profile():
    user = current_user()
    if user is None:
        return jsonify(error='請先登入帳號。'), 401
    db = current_app.extensions['sql']
    member = get_member(db, user['id'])
    if member is None:
        return jsonify(error='尚無個人資料，請登出後重新登入。'), 404
    return jsonify(member=member)


@auth_bp.post('/logout')
def logout():
    expected = session.get('csrf')
    if not expected or not secrets.compare_digest(expected, request.headers.get('X-CSRF-Token', '')):
        return jsonify(error='無效的登出請求。'), 403
    if session.get('login_id'):
        database().delete('login_sessions', {'id': digest(session['login_id'])})
    session.clear()
    return jsonify(authenticated=False)
