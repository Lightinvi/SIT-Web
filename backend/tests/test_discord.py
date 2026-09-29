"""Test Discord pagination, shared caching, rate limits, and failure recovery."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from app import create_app
from app.services.discord import DiscordError, DiscordService


class DiscordTests(unittest.TestCase):
    """Exercise Discord routes and the disk cache with mocked network responses."""
    def setUp(self):
        """Create an app using a temporary Discord cache and a nonproduction bot token."""
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {'TESTING': True, 'DISCORD_BOT_TOKEN': 'test-secret',
                       'DISCORD_CACHE_PATH': str(Path(self.temp.name) / 'cache')}
        self.app = create_app(self.config)
        self.client = self.app.test_client()
        self.service = self.app.extensions['discord']

    def test_daily_cache_persists_and_expires(self):
        """Reuse disk cache across app instances until the exact one-day expiry."""
        with patch.object(DiscordService, '_fetch', return_value=[]) as fetch:
            with patch('app.services.discord.time.time', return_value=1000):
                first = self.client.get('/api/discord/members').json
                self.assertFalse(first['cached'])
                self.assertEqual(first['expires_at'], 87400)
            with patch('app.services.discord.time.time', return_value=87399):
                other = create_app(self.config).test_client()
                self.assertTrue(other.get('/api/discord/members/').json['cached'])
                self.assertEqual(fetch.call_count, 1)
            with patch('app.services.discord.time.time', return_value=87400):
                self.assertFalse(self.client.get('/api/discord/members').json['cached'])
                self.assertEqual(fetch.call_count, 2)

    def test_resources_have_separate_cache(self):
        """Keep member and role caches separate and disable browser caching."""
        with patch.object(self.service, '_fetch', side_effect=[[], [{'id': '10'}]]) as fetch:
            self.client.get('/api/discord/members')
            roles = self.client.get('/api/discord/roles')
            self.assertEqual(roles.json['roles'], [{'id': '10'}])
            self.assertEqual(roles.headers['Cache-Control'], 'no-store')
            self.assertTrue(self.client.get('/api/discord/roles/').json['cached'])
            self.assertEqual(fetch.call_count, 2)

    def test_pagination_and_bot_authorization(self):
        """Fetch subsequent member pages with the bot token and configured network timeout."""
        page = [{'user': {'id': str(i)}} for i in range(1, 1001)]
        responses = [BytesIO(json.dumps(page).encode()), BytesIO(b'[{"user":{"id":"1001"}}]')]
        with patch('app.services.discord.urlopen', side_effect=responses) as request:
            self.assertEqual(len(self.service.get('members')['members']), 1001)
            self.assertTrue(request.call_args_list[0].args[0].full_url.endswith('?limit=1000&after=0'))
            last = request.call_args_list[1].args[0]
            self.assertTrue(last.full_url.endswith('?limit=1000&after=1000'))
            self.assertEqual(last.get_header('Authorization'), 'Bot test-secret')
            self.assertEqual(request.call_args.kwargs['timeout'], 15)

    def test_concurrent_workers_only_refresh_once(self):
        """Ensure concurrent app workers share a single cache refresh."""
        with patch.object(DiscordService, '_fetch', return_value=[]) as fetch:
            def read(_):
                """Read roles through a fresh app instance sharing the test cache directory."""
                return create_app(self.config).extensions['discord'].get('roles')
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(read, range(4)))
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(sum(not item['cached'] for item in results), 1)

    def test_missing_token(self):
        """Return an unavailable response without network access when the bot token is absent."""
        self.service.token = ''
        with patch('app.services.discord.urlopen') as request:
            self.assertEqual(self.client.get('/api/discord/roles').status_code, 503)
            request.assert_not_called()

    def test_rate_limit_backoff_and_recovery(self):
        """Cache rate-limit failures until the retry deadline and then recover."""
        error = HTTPError('https://discord.com', 429, 'limited', {}, BytesIO(b'{"retry_after": 120.5}'))
        with patch('app.services.discord.urlopen', side_effect=[error, BytesIO(b'[]')]) as request:
            with patch('app.services.discord.time.time', return_value=1000):
                first = self.client.get('/api/discord/roles')
                self.assertEqual(first.status_code, 503)
                self.assertEqual(first.headers['Retry-After'], '121')
                self.client.get('/api/discord/roles')
                self.assertEqual(request.call_count, 1)
            with patch('app.services.discord.time.time', return_value=1121):
                self.assertEqual(self.client.get('/api/discord/roles').status_code, 200)
                self.assertEqual(request.call_count, 2)

    def test_failed_page_never_returns_partial_list(self):
        """Reject a multi-page member fetch if any subsequent page fails."""
        page = [{'user': {'id': str(i)}} for i in range(1, 1001)]
        with patch.object(self.service, '_request', side_effect=[page, DiscordError('unavailable')]):
            response = self.client.get('/api/discord/members')
            self.assertEqual(response.status_code, 502)
            self.assertNotIn('members', response.json)

    def test_errors_are_sanitized(self):
        """Ensure upstream exception text cannot expose the bot token to clients."""
        errors = [URLError('test-secret'),
                  HTTPError('https://discord.com', 401, 'test-secret', {}, BytesIO(b'test-secret')),
                  HTTPError('https://discord.com', 403, 'test-secret', {}, BytesIO(b'test-secret'))]
        for error in errors:
            with self.subTest(error=error), patch('app.services.discord.urlopen', side_effect=error):
                with self.assertRaises(DiscordError) as caught:
                    self.service._request('roles')
                self.assertNotIn('test-secret', str(caught.exception))

    def test_invalid_payload_and_nonadvancing_page(self):
        """Reject invalid response shapes and pagination that fails to advance."""
        with patch('app.services.discord.urlopen', return_value=BytesIO(b'{}')):
            with self.assertRaises(DiscordError):
                self.service._request('roles')
        with patch.object(self.service, '_request', return_value=[{'user': {'id': '0'}}]):
            with self.assertRaises(DiscordError):
                self.service._fetch('members')

    def test_json_file_and_corruption_recovery(self):
        """Persist Unicode JSON without credentials and refresh corrupted cache records."""
        path = Path(self.config['DISCORD_CACHE_PATH']) / 'discord-510386488639488001-roles.json'
        with patch.object(self.service, '_fetch', return_value=[{'id': '1', 'name': '隊員'}]) as fetch:
            self.service.get('roles')
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['roles'][0]['name'], '隊員')
            self.assertEqual(saved['expires_at'] - saved['fetched_at'], 86400)
            self.assertNotIn('test-secret', path.read_text())
            for broken in ('{', '[]', '{"expires_at": "bad"}'):
                path.write_text(broken)
                self.assertFalse(self.service.get('roles')['cached'])
            self.assertEqual(fetch.call_count, 4)

    def test_failed_atomic_write_preserves_existing_file(self):
        """Preserve the previous cache and remove temporary files if replacement fails."""
        path = Path(self.config['DISCORD_CACHE_PATH']) / 'discord-510386488639488001-roles.json'
        with patch.object(self.service, '_fetch', return_value=[]):
            with patch('app.services.discord.time.time', return_value=1000):
                self.service.get('roles')
            original = path.read_bytes()
            with patch('app.services.discord.time.time', return_value=90000):
                with patch('app.services.discord.os.replace', side_effect=OSError):
                    with self.assertRaises(DiscordError):
                        self.service.get('roles')
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.glob('*.tmp')), [])
