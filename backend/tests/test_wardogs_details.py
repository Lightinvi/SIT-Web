"""Cross-source joins must use exact IDs and preserve version and field semantics."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from app.services.wardogs_details import item_details


class WardogsDetailTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write('items.json', items=[
            {'id': 'Id.Item.Round.AP', 'tags': ['Item.Caliber.Round', 'Item.Ammo.Type.ArmorPiercing'], 'vendor': []},
            {'id': 'Id.Item.Round', 'vendor': [{'tag': 'Id.Item.Round.AP', 'price': 180}, {'tag': 'Id.Item.Round', 'price': 40}]},
            {'id': 'Id.Item.Rifle', 'description': '', 'weight': 0, 'durability': 10, 'vendor': []},
        ])

    def write(self, filename, **data):
        (self.root / filename).write_text(json.dumps({'gameBuild': '100', **data}))

    def test_caliber_and_ammo_type_join_and_actual_offer_price(self):
        self.write('ammo.json', projectiles=[{'id': 'Item.Caliber.Round', 'damage': 50}])
        self.write('damage.json', ammoTypes=[{'ammoType': 'ArmorPiercing', 'modifier': 0.3}, {'ammoType': 'HollowPoint', 'modifier': 1.5}])
        result = item_details(self.root, 'id.item.round.ap')
        self.assertEqual(result['item']['vendor'], [{'tag': 'Id.Item.Round.AP', 'price': 180}])
        self.assertEqual([section['records'] for section in result['sections']], [[{'id': 'Item.Caliber.Round', 'damage': 50}], [{'ammoType': 'ArmorPiercing', 'modifier': 0.3}]])

    def test_fill_missing_fields_without_overwriting_zero_or_including_durability(self):
        self.write('weapons.json', weapons=[{'id': 'ID.ITEM.RIFLE', 'description': 'Rifle details', 'weight': 9, 'rpm': 700, 'durability': 300}])
        result = item_details(self.root, 'Id.Item.Rifle')
        self.assertEqual(result['item']['description'], 'Rifle details')
        self.assertEqual(result['item']['weight'], 0)
        self.assertNotIn('durability', result['item'])
        self.assertNotIn('durability', result['sections'][0]['records'][0])

    def test_reject_mismatched_build_and_substring_only_matches(self):
        self.write('weapons.json', gameBuild='other', weapons=[{'id': 'Id.Item.Rifle', 'rpm': 700}])
        self.write('attachments.json', attachments=[{'id': 'Id.Item.Rifle.Stock', 'name': 'Id.Item.Rifle copy'}])
        result = item_details(self.root, 'Id.Item.Rifle')
        self.assertEqual(result['sections'], [])
        self.assertIsNone(item_details(self.root, 'missing'))

    def test_ammo_base_damage_and_weapon_links_use_same_build_caliber(self):
        self.write('items.json', items=[{'id': 'Round', 'tags': ['Item.Ammo', 'Item.Caliber.556mm']}, {'id': 'Rifle', 'name': 'Rifle'}])
        self.write('ammo.json', projectiles=[{'id': 'Item.Caliber.556mm', 'items': ['ROUND'], 'damage': 28}])
        self.write('weapons.json', weapons=[{'id': 'Rifle', 'calibers': ['556mm']}, {'id': 'MissingWeapon', 'calibers': ['556mm']}, {'id': 'Other', 'calibers': ['9mm']}])
        result = item_details(self.root, 'Round')['ammoDetails']
        self.assertEqual(result['damage'], 28)
        self.assertEqual(result['weapons'], [{'id': 'Rifle', 'name': 'Rifle'}])
        self.write('ammo.json', gameBuild='other', projectiles=[{'id': 'Item.Caliber.556mm', 'damage': 999}])
        self.assertIsNone(item_details(self.root, 'Round')['ammoDetails']['damage'])

    def test_sourced_price_only_fills_missing_vendor_prices_for_verified_build(self):
        self.write('items.json', gameBuild='25937608', items=[{'id': 'Id.Item.AK74M', 'vendor': []}])
        result = item_details(self.root, 'Id.Item.AK74M')
        self.assertEqual(result['item']['vendor'][0]['price'], 800)
        self.assertIn('steampowered.com', result['priceSource']['source'])
        self.write('items.json', gameBuild='25937608', items=[{'id': 'Id.Item.AK74M', 'vendor': [{'tag': 'Id.Item.AK74M', 'price': 0}]}])
        result = item_details(self.root, 'Id.Item.AK74M')
        self.assertEqual(result['item']['vendor'][0]['price'], 0)
        self.assertIsNone(result['priceSource'])
        self.write('items.json', gameBuild='new-build', items=[{'id': 'Id.Item.AK74M', 'vendor': []}])
        result = item_details(self.root, 'Id.Item.AK74M')
        self.assertEqual(result['item']['vendor'], [])
        self.assertIsNone(result['priceSource'])
