"""Discord OAuth requests; credentials and tokens never leave the backend."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class OAuthError(Exception):
    pass


def discord_request(path, *, token=None, data=None):
    headers = {'User-Agent': 'SIT-Web OAuth/1.0'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    request = Request('https://discord.com/api/v10/' + path, headers=headers,
                      data=urlencode(data).encode() if data is not None else None)
    try:
        with urlopen(request, timeout=15) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise OAuthError('discord_unavailable')
        return result
    except HTTPError as error:
        status = error.code
        error.close()
        if status == 404 and path.endswith('/member'):
            raise OAuthError('not_member') from None
        raise OAuthError('discord_unavailable') from None
    except (URLError, OSError, ValueError):
        raise OAuthError('discord_unavailable') from None


def authenticate(code, config):
    credentials = discord_request('oauth2/token', data={
        'client_id': config['DISCORD_CLIENT_ID'],
        'client_secret': config['DISCORD_CLIENT_SECRET'],
        'grant_type': 'authorization_code', 'code': code,
        'redirect_uri': config['DISCORD_REDIRECT_URI'],
    })
    token = credentials.get('access_token')
    if not isinstance(token, str) or not token:
        raise OAuthError('discord_unavailable')
    user = discord_request('users/@me', token=token)
    guild = config['DISCORD_GUILD_ID']
    member = discord_request(f'users/@me/guilds/{guild}/member', token=token)
    if not user.get('id') or member.get('user', {}).get('id') != user['id']:
        raise OAuthError('not_member')
    if member.get('pending'):
        raise OAuthError('pending_member')
    avatar = member.get('avatar')
    if avatar:
        avatar_url = f"https://cdn.discordapp.com/guilds/{guild}/users/{user['id']}/avatars/{avatar}.png?size=256"
    elif user.get('avatar'):
        avatar_url = f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.png?size=256"
    else:
        discriminator = user.get('discriminator', '0')
        index = int(discriminator) % 5 if discriminator != '0' else (int(user['id']) >> 22) % 6
        avatar_url = f'https://cdn.discordapp.com/embed/avatars/{index}.png'
    return {'global_name': user.get('global_name'), 'nickname': member.get('nick'),
            'avatar_url': avatar_url, 'guild_joined_at': member.get('joined_at'),
            'id': user['id'], 'name': member.get('nick') or user.get('global_name') or user.get('username'),
            'username': user.get('username')}
