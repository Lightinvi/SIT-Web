import unittest
from app.services.wardogs_simulation import simulation_data

class SimulationTests(unittest.TestCase):
    def test_only_matching_caliber_ammo_and_same_build_stats_are_linked(self):
        sources = {
            'items.json': {'gameBuild': '1', 'items': [
                {'id': 'Round', 'name': 'Round', 'tags': ['Item.Ammo', 'Item.Caliber.556mm']},
                {'id': 'Wrong', 'tags': ['Item.Ammo', 'Item.Caliber.9mm']},
                {'id': 'Magazine', 'tags': ['Item.Attachment.Magazine', 'Item.Caliber.556mm']},
            ]},
            'ammo.json': {'gameBuild': '1', 'projectiles': [{'id': 'Item.Caliber.556mm', 'items': ['ROUND'], 'damage': 28}]},
            'equipment.json': {'gameBuild': 'other', 'armor': [{'id': 'bad'}]},
        }
        model = simulation_data(sources, {'id': 'Rifle', 'tags': ['Item.Archetype.AR']}, {'calibers': ['556mm']})
        self.assertEqual([row['id'] for row in model['ammo']], ['Round'])
        self.assertEqual(model['ammo'][0]['projectile']['damage'], 28)
        self.assertEqual(model['armor'], [])
