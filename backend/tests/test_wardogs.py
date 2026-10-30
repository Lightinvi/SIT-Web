"""Verify persistent release caching, refresh boundaries, and failure fallback."""
import json
from io import BytesIO
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from app.services.wardogs import WardogsService, WEEK, WardogsError


class WardogsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.service = WardogsService(self.temp.name)
        root = Path(self.temp.name) / '123'
        (root / 'data').mkdir(parents=True)
        (root / 'data' / 'items.json').write_text(json.dumps({'gameBuild': '100', 'items': [{'id': 'item'}]}))
        self.service._save({'release': '123', 'cacheVersion': 2, 'checkedAt': 1000, 'updatedAt': 1000, 'nextCheck': 1000 + WEEK})

    def test_reuses_disk_across_instances_until_week_boundary(self):
        other = WardogsService(self.temp.name)
        with patch('app.services.wardogs.time.time', return_value=1000 + WEEK - 1), patch.object(other, '_json') as request:
            self.assertEqual(other.get()['gameBuild'], '100')
            request.assert_not_called()
        with patch('app.services.wardogs.time.time', return_value=1000 + WEEK), patch.object(other, '_json', return_value={'id': 123}) as request:
            self.assertEqual(other.get()['checkedAt'], 1000 + WEEK)
            request.assert_called_once()

    def test_failed_update_preserves_snapshot_and_backs_off(self):
        with patch.object(self.service, '_json', side_effect=OSError('offline')):
            with self.assertRaises(WardogsError):
                self.service.get(force=True)
        self.assertEqual(self.service.read()['items'], [{'id': 'item'}])
        self.assertTrue(self.service.read()['stale'])

    def test_force_checks_even_if_not_due(self):
        with patch.object(self.service, '_json', return_value={'id': 123}) as request:
            self.assertEqual(self.service.get(force=True)['release'], '123')
            request.assert_called_once()

    def test_same_release_upgrade_downloads_every_dataset_and_asset(self):
        state = self.service._state()
        state.pop('cacheVersion')
        self.service._save(state)
        archive = BytesIO()
        contents = {
            'data/items.json': json.dumps({'gameBuild': '100', 'items': [{'id': 'item'}]}),
            'data/weapons.json': '{}', 'data/ammo.json': '{}',
            'data/maps/europe/terrain.json': '{}', 'data/csv/weapons.csv': 'id,name',
            'data/schema/weapons.schema.json': '{}', 'data/MANIFEST.json': '{}',
            'assets/icons/example.png': 'icon', 'assets/maps/europe/heightmap.png': 'heightmap',
            'assets/maps/europe/tiles/0/0/0.webp': 'tile', 'assets/icons.manifest.json': '{}',
            'README.md': 'readme', 'LICENSE': 'license',
            '../escape.txt': 'bad', '/absolute.txt': 'bad',
        }
        with zipfile.ZipFile(archive, 'w') as bundle:
            for filename, content in contents.items():
                bundle.writestr(filename, content)
        archive.seek(0)
        release = {'id': 123, 'assets': [{'name': 'data-full.zip', 'browser_download_url': 'https://github.com/warpuppies/wardogs-data/releases/download/build/data-full.zip'}]}
        with patch.object(self.service, '_json', return_value=release), patch('app.services.wardogs.urlopen', return_value=archive):
            result = self.service.get()
        self.assertEqual(result['cacheVersion'], 2)
        root = self.service.path / '123'
        for filename in contents:
            if not filename.startswith(('../', '/')):
                self.assertEqual((root / filename).read_text(), contents[filename])
        self.assertFalse((self.service.path / 'escape.txt').exists())
        self.assertTrue((root / 'data' / 'items.json').is_file())
        self.assertFalse((root / 'items.json').exists())
        self.assertEqual(result['items'], [{'id': 'item'}])

    def test_source_file_endpoints_serve_nested_data_and_reject_traversal(self):
        from app import create_app
        app = create_app({'TESTING': True, 'DISCORD_CACHE_PATH': str(self.service.path / 'cache')})
        app.extensions['wardogs'] = self.service
        root = self.service.path / '123' / 'data' / 'maps' / 'europe'
        root.mkdir(parents=True)
        (root / 'terrain.json').write_text('{"height": 10}')
        client = app.test_client()
        with client.get('/api/wardogs/data/123/maps/europe/terrain.json') as response:
            self.assertEqual(response.json, {'height': 10})
        self.assertEqual(client.get('/api/wardogs/data/123/../../state.json').status_code, 404)
        self.assertEqual(client.get('/api/wardogs/data/bad/state.json').status_code, 404)
        with patch.object(self.service, 'read', return_value={'release': '123', 'gameBuild': '100', 'cacheVersion': 2}):
            result = client.get('/api/wardogs/datasets').json
        self.assertTrue(result['complete'])
        self.assertEqual(result['files'], ['items.json', 'maps/europe/terrain.json'])

    def test_legacy_items_move_into_data_without_network(self):
        root = self.service.path / '123'
        (root / 'data' / 'items.json').rename(root / 'items.json')
        with patch('app.services.wardogs.time.time', return_value=1001), patch.object(self.service, '_json') as request:
            self.assertEqual(self.service.get()['items'], [{'id': 'item'}])
            request.assert_not_called()
        self.assertTrue((root / 'data' / 'items.json').is_file())
        self.assertFalse((root / 'items.json').exists())

    def test_canonical_items_take_precedence_over_legacy_duplicate(self):
        root = self.service.path / '123'
        (root / 'items.json').write_text('{"items": []}')
        self.assertEqual(self.service.read()['items'], [{'id': 'item'}])
        self.assertFalse((root / 'items.json').exists())
