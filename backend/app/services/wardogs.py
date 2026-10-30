"""Persistent Wardogs release snapshots with weekly checks and local item icons."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import time
import threading
from urllib.request import Request, urlopen
import zipfile

WEEK = 7 * 86400
CACHE_VERSION = 2
RELEASE_URL = 'https://api.github.com/repos/warpuppies/wardogs-data/releases/latest'


class WardogsError(Exception):
    """Public cache availability error."""


class WardogsService:
    def __init__(self, path):
        self.path = Path(path)
        self._updating = threading.Lock()
        self.error = None

    def status(self):
        state = self._state()
        running = self._updating.locked()
        if self.path.exists():
            with (self.path / 'update.lock').open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    running = True
        return {**(state or {}), 'ready': state is not None, 'running': running,
                'error': self.error or ('更新失敗，已保留原有資料。' if state and state.get('stale') else None)}

    def start_update(self):
        if self._updating.acquire(blocking=False):
            def run():
                try:
                    self.error = None
                    self.get(force=True)
                except Exception:
                    self.error = '更新失敗，請稍後重試。'
                finally:
                    self._updating.release()
            threading.Thread(target=run, daemon=True).start()
        return self.status()

    def read(self):
        state = self._state()
        if not state or (state.get('cacheVersion') != CACHE_VERSION and not state.get('stale')) or time.time() >= state.get('nextCheck', 0):
            self.start_update()
        if not state:
            raise WardogsError('正在準備 WARDOGS 資料與圖片，請稍後重新載入。')
        data = json.loads((self.path / state['release'] / 'data' / 'items.json').read_text())
        return {**data, **state}

    def _json(self, url):
        with urlopen(Request(url, headers={'User-Agent': 'SIT-Web Wardogs cache'}), timeout=60) as response:
            return json.load(response)

    @contextmanager
    def _lock(self):
        self.path.mkdir(parents=True, exist_ok=True)
        with (self.path / 'update.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def _state(self):
        try:
            state = json.loads((self.path / 'state.json').read_text())
            if not str(state['release']).isdigit():
                return None
            root = self.path / str(state['release'])
            canonical = root / 'data' / 'items.json'
            legacy = root / 'items.json'
            if not canonical.is_file() and legacy.is_file():
                canonical.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(legacy, canonical)
                except FileNotFoundError:
                    pass  # Another worker may have completed the same migration.
            if not canonical.is_file():
                return None
            legacy.unlink(missing_ok=True)
            return state
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _save(self, state):
        temporary = self.path / 'state.tmp'
        temporary.write_text(json.dumps(state))
        os.replace(temporary, self.path / 'state.json')

    def get(self, force=False):
        with self._lock():
            state = self._state()
            if force or not state or (state.get('cacheVersion') != CACHE_VERSION and not state.get('stale')) or time.time() >= state.get('nextCheck', 0):
                try:
                    release = self._json(RELEASE_URL)
                    release_id = str(int(release['id']))
                    if not state or state['release'] != release_id or state.get('cacheVersion') != CACHE_VERSION:
                        asset = next(asset for asset in release['assets'] if asset['name'].endswith('-full.zip'))
                        url = asset['browser_download_url']
                        if not url.startswith('https://github.com/warpuppies/wardogs-data/releases/download/'):
                            raise ValueError('Unexpected release URL')
                        with tempfile.TemporaryDirectory(dir=self.path) as temporary:
                            root = Path(temporary)
                            archive = root / 'release.zip'
                            with urlopen(Request(url, headers={'User-Agent': 'SIT-Web Wardogs cache'}), timeout=60) as response, archive.open('wb') as output:
                                shutil.copyfileobj(response, output)
                            snapshot = root / 'snapshot'
                            snapshot.mkdir()
                            with zipfile.ZipFile(archive) as bundle:
                                for entry in bundle.infolist():
                                    parts = PurePosixPath(entry.filename).parts
                                    if '..' in parts or entry.is_dir():
                                        continue
                                    # Preserve all published data and assets, including nested
                                    # maps, CSV, schemas, manifests, README and license files.
                                    if PurePosixPath(entry.filename).is_absolute() or '\\' in entry.filename:
                                        continue
                                    relative = PurePosixPath(entry.filename)
                                    if parts[0] not in ('data', 'assets'):
                                        if len(parts) > 1 and parts[1] in ('data', 'assets'):
                                            relative = PurePosixPath(*parts[1:])
                                        elif relative.name not in ('README.md', 'LICENSE'):
                                            continue
                                    target = snapshot / relative
                                    target.parent.mkdir(parents=True, exist_ok=True)
                                    with bundle.open(entry) as source, target.open('wb') as output:
                                        shutil.copyfileobj(source, output)
                            data = json.loads((snapshot / 'data' / 'items.json').read_text())
                            if not isinstance(data.get('items'), list) or not isinstance(data.get('gameBuild'), str):
                                raise ValueError('Invalid Wardogs data')
                            if not (snapshot / 'assets' / 'icons').is_dir():
                                raise ValueError('Missing Wardogs icons')
                            (snapshot / 'icons').symlink_to('assets/icons', target_is_directory=True)
                            destination = self.path / release_id
                            if not destination.exists():
                                os.replace(snapshot, destination)
                            else:
                                # Same-release upgrades retain existing item/icon URLs.
                                for child in snapshot.iterdir():
                                    if child.name == 'icons':
                                        continue
                                    target = destination / child.name
                                    if target.exists():
                                        shutil.rmtree(target) if target.is_dir() else target.unlink()
                                    os.replace(child, target)
                        state = {'release': release_id, 'gameBuild': data['gameBuild'], 'cacheVersion': CACHE_VERSION, 'updatedAt': time.time()}
                    state.update(checkedAt=time.time(), nextCheck=time.time() + WEEK, stale=False)
                    self._save(state)
                except Exception as error:
                    if not state:
                        raise WardogsError('WARDOGS 資料尚未備妥，請管理員更新資料。') from error
                    state.update(stale=True, nextCheck=time.time() + 3600)
                    self._save(state)
                    if force:
                        raise WardogsError('更新失敗，已保留原有 WARDOGS 資料。') from error
            data = json.loads((self.path / state['release'] / 'data' / 'items.json').read_text())
            return {**data, **state}
