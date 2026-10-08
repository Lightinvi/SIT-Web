"""Discord Bot reads with a persistent, process-shared daily cache."""
from contextlib import contextmanager
import fcntl
import json
import math
from pathlib import Path
import os
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class DiscordError(Exception):
    """Carry a client-safe message, HTTP status, and retry delay for Discord failures."""
    def __init__(self, message, status=502, retry_after=60):
        """Associate a sanitized message with response status and retry delay in seconds.
        設定可公開的 Discord 錯誤訊息、HTTP 狀態及重試等待秒數。

        Args:
            message: 可公開的錯誤訊息。
            status: HTTP 回應狀態碼。 預設為 502。
            retry_after: 建議重試等待秒數。 預設為 60。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> result = DiscordError(message=message)
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class DiscordService:
    """Read guild resources through a disk cache shared by application workers."""
    def __init__(self, token, guild_id, cache_path):
        """Store the bot token, guild ID, and cache directory without making network calls.
        儲存 Bot 權杖、群組 ID 與快取路徑，不立即連線。

        Args:
            token: Discord 驗證權杖；不得寫入公開日誌。
            guild_id: Discord 群組 ID 字串。
            cache_path: 共享 Discord 快取目錄路徑。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Example:
            >>> result = DiscordService(token=token, guild_id=guild_id, cache_path=cache_path)
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        self.token = token
        self.guild_id = guild_id
        self.cache_path = Path(cache_path)

    def _request(self, resource, query='', *, path=None, payload=None):
        """Fetch one Discord list response with bot authorization and a 15-second timeout.

        Validate the response shape and translate upstream failures into sanitized
        DiscordError instances, preserving a usable rate-limit retry delay.
        透過 Bot 驗證存取 Discord，檢查回應格式並轉換上游錯誤。

        Args:
            resource: Discord 資源名稱或群組內相對路徑。
            query: 附加於群組資源路徑的 URL 查詢字串。 預設為 ''。
            path: 覆寫群組資源路徑的 Discord API 相對端點，或 None。 預設為 None。
            payload: 傳送給 Discord API 的 JSON 請求資料，或 None 使用 GET。 預設為 None。

        Returns:
            dict | list[dict]: 經驗證的成員、邀請或資源清單。

        Exceptions:
            DiscordError: Discord 存取、回應格式或快取服務無法完成操作。 若由下列處理流程捕捉，則依其轉換規則處理。
            HTTPError: 捕捉後轉換為上列業務或驗證例外。
            URLError, OSError, ValueError: 捕捉後轉換為上列業務或驗證例外。
            ValueError, TypeError, AttributeError: 已在函式內捕捉，使用備援流程、略過無效資料或完成清理。

        Example:
            >>> result = instance._request(resource="members")
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        request = Request(
            f'https://discord.com/api/v10/{path or f"guilds/{self.guild_id}/{resource}{query}"}',
            data=json.dumps(payload).encode() if payload is not None else None,
            method='POST' if payload is not None else 'GET',
            headers={'Authorization': f'Bot {self.token}',
                     'Content-Type': 'application/json',
                     'User-Agent': 'SIT-Web (Discord guild reader, 1.0)'},
        )
        try:
            with urlopen(request, timeout=15) as response:
                data = json.load(response)
        except HTTPError as error:
            retry_after = 60
            if error.code == 429:
                try:
                    retry = float(json.load(error).get('retry_after', 60))
                    if math.isfinite(retry):
                        retry_after = max(1, math.ceil(retry))
                except (ValueError, TypeError, AttributeError):
                    pass
            error.close()
            messages = {
                401: 'Discord Bot 驗證失敗，請確認 DISCORD_BOT_TOKEN。',
                403: 'Discord 拒絕存取，請確認 Bot 的頻道與角色權限，以及 Server Members Intent 設定。',
                404: '找不到 Discord 群組或資源。',
                429: 'Discord 請求過於頻繁，請稍後再試。',
            }
            raise DiscordError(messages.get(error.code, 'Discord 服務暫時無法使用。'),
                               503 if error.code == 429 else 502, retry_after) from None
        except (URLError, OSError, ValueError):
            raise DiscordError('無法讀取 Discord 資料，請稍後再試。') from None
        if path is not None:
            from app.models.invitation import valid_code
            if not isinstance(data, dict) or not valid_code(data.get('code')):
                raise DiscordError('Discord 回傳的邀請格式不正確。')
            return data
        if resource.startswith('members/'):
            if not isinstance(data, dict) or not isinstance(data.get('roles'), list):
                raise DiscordError('Discord 回傳的資料格式不正確。')
            return data
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise DiscordError('Discord 回傳的資料格式不正確。')
        return data

    def create_invite(self, channel_id, role_ids, temporary):
        """Create a fresh single-use ten-minute invite with membership settings.
        依指定身份組與暫時成員設定，建立十分鐘有效且限用一次的 Discord 邀請。

        Args:
            channel_id: Discord 邀請目標頻道 ID。
            role_ids: Discord 身份組 ID 清單。
            temporary: 是否建立暫時成員邀請。

        Returns:
            str: Discord 回傳的新邀請代碼。

        Exceptions:
            DiscordError: Discord 存取、回應格式或快取服務無法完成操作。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> result = instance.create_invite(channel_id="123456789012345678", role_ids=["578156037589172244"], temporary=True)
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        from app.models.invitation import INVITE_MAX_AGE
        if not self.token:
            raise DiscordError('尚未設定 DISCORD_BOT_TOKEN。', 503)
        payload = {'max_age': INVITE_MAX_AGE, 'max_uses': 1,
                   'unique': True, 'temporary': temporary}
        if role_ids:
            payload['role_ids'] = role_ids
        return self._request('invites', path=f'channels/{channel_id}/invites',
                             payload=payload)['code']

    def find_administrator(self, username, role_ids):
        """Verify a referral username against live guild members with configured roles.

        Bypass the daily public cache so removed administrators cannot keep issuing
        website referrals. Return stable ID and current username, or None.
        查詢即時群組成員，依 username 與管理員身份組驗證推薦人。

        Args:
            username: 要驗證的 Discord username。
            role_ids: Discord 身份組 ID 清單。

        Returns:
            dict | None: 管理員 id、username，無匹配時為 None。

        Exceptions:
            DiscordError: Discord 存取、回應格式或快取服務無法完成操作。 若由下列處理流程捕捉，則依其轉換規則處理。

        Example:
            >>> result = instance.find_administrator(username="example_admin", role_ids=["578156037589172244"])
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        if not self.token:
            raise DiscordError('管理員代碼驗證尚未設定，請稍後再試。', 503)
        for member in self._fetch('members'):
            user = member.get('user', {})
            if (user.get('username', '').casefold() == username.casefold()
                    and not user.get('bot') and not member.get('pending')
                    and set(member.get('roles', [])).intersection(role_ids)):
                return {'id': user['id'], 'username': user['username']}
        return None

    def _fetch(self, resource):
        """Return all roles or collect every member page in increasing snowflake order.

        Reject duplicate or nonadvancing member IDs rather than return a partial list.
        取得全部身份組或逐頁取得成員，拒絕重複及未前進的成員分頁。

        Args:
            resource: Discord 資源名稱或群組內相對路徑。

        Returns:
            list[dict]: 完整身份組或成員清單。

        Exceptions:
            ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
            DiscordError: Discord 存取、回應格式或快取服務無法完成操作。 若由下列處理流程捕捉，則依其轉換規則處理。
            KeyError, TypeError, ValueError: 捕捉後轉換為上列業務或驗證例外。

        Example:
            >>> result = instance._fetch(resource="members")
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        if resource == 'roles':
            return self._request('roles')
        members = []
        after = 0
        while True:
            page = self._request('members', f'?limit=1000&after={after}')
            try:
                ids = [int(member['user']['id']) for member in page]
                if any(member_id <= after for member_id in ids) or len(set(ids)) != len(ids):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise DiscordError('Discord 成員分頁資料不正確。') from None
            members.extend(page)
            if len(page) < 1000:
                return members
            after = max(ids)

    @contextmanager
    def _lock(self, path):
        # Keep the lock file: unlinking it could split workers across two locks.
        """Hold an exclusive cache-file lock, waiting at most twenty seconds.

        Keep the lock file on disk so workers continue locking the same inode.
        取得跨程序快取檔案鎖，最多等候二十秒並於離開時釋放。

        Args:
            path: 要讀寫或鎖定的快取檔案路徑。

        Returns:
            ContextManager[None]: 持有檔案鎖的 with 區塊。

        Exceptions:
            DiscordError: Discord 存取、回應格式或快取服務無法完成操作。 若由下列處理流程捕捉，則依其轉換規則處理。
            BlockingIOError: 捕捉後轉換為上列業務或驗證例外。

        Example:
            >>> with instance._lock(path=path) as context:
            ...     pass
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        with path.open('a') as lock:
            deadline = time.monotonic() + 20
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise DiscordError('Discord 快取更新中，請稍後再試。', 503)
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _read_cache(self, path, resource):
        """Return a structurally valid success or error record, or None for invalid JSON.

        Expiration is checked by get, not by this reader.
        讀取並驗證成功或錯誤快取，無效內容回傳空值，期限由 get 判斷。

        Args:
            path: 要讀寫或鎖定的快取檔案路徑。
            resource: Discord 資源名稱或群組內相對路徑。

        Returns:
            dict | None: 結構有效的快取紀錄，缺失或無效時為 None。

        Exceptions:
            FileNotFoundError, ValueError, KeyError, TypeError: 已在函式內捕捉，使用備援流程、略過無效資料或完成清理。

        Example:
            >>> result = instance._read_cache(path=path, resource="members")
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        try:
            record = json.loads(path.read_text(encoding='utf-8'))
            expires = record['expires_at']
            valid_data = (isinstance(record.get(resource), list)
                          and isinstance(record.get('fetched_at'), (int, float)))
            valid_error = (isinstance(record.get('error'), str)
                           and record.get('status') in (502, 503))
            if (isinstance(expires, (int, float)) and math.isfinite(expires)
                    and (valid_data or valid_error)):
                return record
        except (FileNotFoundError, ValueError, KeyError, TypeError):
            pass
        return None

    def _write_cache(self, path, record):
        """Atomically replace cached JSON after flushing it to disk.

        Clean up unfinished temporary files and propagate filesystem failures.
        將 JSON 快取同步至磁碟後原子替換檔案，清理未完成的暫存檔。

        Args:
            path: 要讀寫或鎖定的快取檔案路徑。
            record: 待儲存的 JSON 快取對照表。

        Returns:
            None: 僅更新狀態或執行副作用，不回傳資料。

        Exceptions:
            執行期間的例外: finally 完成資源清理後，仍向呼叫者傳遞。

        Example:
            >>> result = instance._write_cache(path=path, record=record)
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w', encoding='utf-8', dir=self.cache_path,
                prefix=path.stem + '-', suffix='.tmp', delete=False,
            ) as output:
                temporary = Path(output.name)
                json.dump(record, output, ensure_ascii=False, indent=2)
                output.write('\n')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def get(self, resource, *, force=False):
        """Return members or roles with cache timestamps and a cached flag.

        Reuse successful data for one day and cache failures for their retry interval.
        Refresh under a process-shared lock; raise DiscordError while an error is cached.
        取得成員或身份組快取，必要時在共享鎖內更新並保留失敗重試期限。

        Args:
            resource: Discord 資源名稱或群組內相對路徑。
            force: 是否強制更新快取，即使現有快取尚未到期。 預設為 False。

        Returns:
            dict: 資源資料、取得時間、到期時間及 cached 標記。

        Exceptions:
            DiscordError: Discord 存取、回應格式或快取服務無法完成操作。 若由下列處理流程捕捉，則依其轉換規則處理。
            ValueError: 名稱、格式、數值或參數組合未通過驗證。 若由下列處理流程捕捉，則依其轉換規則處理。
            OSError: 捕捉後轉換為上列業務或驗證例外。
            DiscordError: 已在函式內捕捉，使用備援流程、略過無效資料或完成清理。

        Example:
            >>> result = instance.get(resource="members")
            db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
        """
        if not self.token:
            raise DiscordError('尚未設定 DISCORD_BOT_TOKEN。', 503)
        if resource not in ('members', 'roles'):
            raise ValueError('Unsupported Discord resource')
        if not str(self.guild_id).isdigit():
            raise ValueError('Invalid Discord guild ID')
        path = self.cache_path / f'discord-{self.guild_id}-{resource}.json'
        try:
            self.cache_path.mkdir(parents=True, exist_ok=True)
            with self._lock(path.with_suffix('.lock')):
                result = self._read_cache(path, resource)
                cached = not force and result is not None and result['expires_at'] > time.time()
                if not cached:
                    try:
                        data = self._fetch(resource)
                        fetched_at = time.time()
                        result = {resource: data, 'fetched_at': fetched_at,
                                  'expires_at': fetched_at + 86400}
                    except DiscordError as error:
                        # Short backoff prevents failed requests from hammering Discord.
                        result = {'error': str(error), 'status': error.status,
                                  'expires_at': time.time() + error.retry_after}
                    self._write_cache(path, result)
            if 'error' in result:
                raise DiscordError(result['error'], result['status'],
                                   max(1, math.ceil(result['expires_at'] - time.time())))
            return {**result, 'cached': cached}
        except OSError:
            raise DiscordError('Discord 快取暫時無法使用，請稍後再試。', 503) from None
