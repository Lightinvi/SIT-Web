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
    def __init__(self, message, status=502, retry_after=60):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class DiscordService:
    def __init__(self, token, guild_id, cache_path):
        self.token = token
        self.guild_id = guild_id
        self.cache_path = Path(cache_path)

    def _request(self, resource, query=''):
        request = Request(
            f'https://discord.com/api/v10/guilds/{self.guild_id}/{resource}{query}',
            headers={'Authorization': f'Bot {self.token}',
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
                403: 'Discord 拒絕存取，請確認 Bot 已加入群組，並啟用 Server Members Intent。',
                404: '找不到 Discord 群組或資源。',
                429: 'Discord 請求過於頻繁，請稍後再試。',
            }
            raise DiscordError(messages.get(error.code, 'Discord 服務暫時無法使用。'),
                               503 if error.code == 429 else 502, retry_after) from None
        except (URLError, OSError, ValueError):
            raise DiscordError('無法讀取 Discord 資料，請稍後再試。') from None
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise DiscordError('Discord 回傳的資料格式不正確。')
        return data

    def _fetch(self, resource):
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

    def get(self, resource):
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
                cached = result is not None and result['expires_at'] > time.time()
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
