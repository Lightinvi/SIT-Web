"""Discord OAuth requests; credentials and tokens never leave the backend."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class OAuthError(Exception):
    """Represent a public authentication failure code without exposing credentials."""
    pass


def discord_request(path, *, token=None, data=None):
    """Call Discord with an optional bearer token or form-encoded POST payload.

    Return a JSON object. Raise OAuthError for network, payload, or API failures;
    a missing guild membership is distinguished from a general upstream failure.
    透過 OAuth 存取 Discord，將網路及格式錯誤轉成公開登入錯誤碼。

    Args:
        path: Discord API v10 的相對端點路徑。
        token: Discord 驗證權杖；不得寫入公開日誌。 預設為 None。
        data: 操作所需的資料對照表。 預設為 None。

    Returns:
        dict: Discord OAuth API 的 JSON 物件。

    Exceptions:
        OAuthError: Discord OAuth 或即時群組身份驗證失敗。 若由下列處理流程捕捉，則依其轉換規則處理。
        HTTPError: 捕捉後轉換為上列業務或驗證例外。
        URLError, OSError, ValueError: 捕捉後轉換為上列業務或驗證例外。

    Example:
        >>> result = discord_request(path=path)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
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
    """Exchange an OAuth code and verify the user's current membership in the guild.

    Return identity, display-name, avatar, and join-date fields without tokens.
    Reject mismatched identities, pending screening, and missing login roles.
    Check live OAuth membership, never the public member cache or saved profile.
    交換 OAuth 代碼並即時驗證群組成員及登入身份組，回傳不含權杖的用戶資料。

    Args:
        code: Discord OAuth 回呼提供的一次性授權碼。
        config: 應用程式配置對照表。

    Returns:
        dict: 即時驗證後的用戶資料，不包含存取權杖。

    Exceptions:
        OAuthError: Discord OAuth 或即時群組身份驗證失敗。 若由下列處理流程捕捉，則依其轉換規則處理。

    Example:
        >>> result = authenticate(code=code, config=config)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return OAuthService(config).authenticate(code)


class OAuthService:
    """Verify live Discord membership using application-owned OAuth settings.
    以應用程式所屬 OAuth 設定驗證即時群組成員資格。
    """

    def __init__(self, config):
        """Store the dependencies owned by this object.
        儲存物件的相依項目，供各操作重用。

        Args:
            config: 此應用程式的 OAuth 與群組驗證設定。

        Returns:
            None: 完成物件初始化。

        Example:
            >>> service = OAuthService(config)
            相依項目須先依 Args 建立。
        """
        self.config = config

    def authenticate(self, code):
        """Exchange an OAuth code and verify the user's current membership in the guild.

        Return identity, display-name, avatar, and join-date fields without tokens.
        Reject mismatched identities, pending screening, and missing login roles.
        Check live OAuth membership, never the public member cache or saved profile.
        交換 OAuth 代碼並即時驗證群組成員及登入身份組，回傳不含權杖的用戶資料。

        Args:
            code: Discord OAuth 回呼提供的一次性授權碼。

        Returns:
            dict: 即時驗證後的用戶資料，不包含存取權杖。

        Exceptions:
            OAuthError: Discord OAuth 或即時群組身份驗證失敗。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> service = OAuthService(config)
            >>> result = service.authenticate(code=code)
            相依物件與操作輸入須先依 Args 建立；成員 ID 須對應既有測試資料。
        """
        config = self.config
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
        roles = member.get('roles')
        if not isinstance(roles, list) or not all(isinstance(role, str) for role in roles):
            raise OAuthError('insufficient_role')
        if not set(roles).intersection(config.get('DISCORD_LOGIN_ROLE_IDS', ())):
            raise OAuthError('insufficient_role')
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
                'username': user.get('username'), 'role_ids': roles}
