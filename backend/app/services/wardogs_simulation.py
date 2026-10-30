"""Build a same-build simulation input using caliber tags and source damage rules."""
import re


def simulation_data(sources, item, weapon):
    build = sources['items.json']['gameBuild']
    def rows(file, key):
        source = sources.get(file, {})
        return source.get(key, []) if source.get('gameBuild') == build else []
    projectiles = rows('ammo.json', 'projectiles')
    calibers = {'item.caliber.' + caliber.casefold() for caliber in weapon.get('calibers', [])}
    ammo = []
    for candidate in sources['items.json']['items']:
        tags = [tag.casefold() for tag in candidate.get('tags', [])]
        if 'item.ammo' not in tags or not calibers.intersection(tags):
            continue
        projectile = next((row for row in projectiles if any(identifier.casefold() == candidate['id'].casefold() for identifier in row.get('items', []))), None)
        if projectile is None:
            projectile = next((row for row in projectiles if row['id'].casefold() in tags), None)
        ammo_type = next((tag[len('Item.Ammo.Type.'):] for tag in candidate.get('tags', []) if tag.casefold().startswith('item.ammo.type.')), 'FMJ')
        ammo.append({'id': candidate['id'], 'name': candidate.get('name', candidate['id']), 'icon': candidate.get('icon'),
                     'ammoType': ammo_type, 'projectile': projectile})
    tables = rows('damage.json', 'hitLocationMultipliers')
    classes = [tag.replace('Item.Archetype.', 'Weapon.') for tag in item.get('tags', []) if tag.startswith('Item.Archetype.')]
    if 'Weapon.Bow' in classes:
        classes.append('Weapon.CombatBow')
    class_table = next((table for table in tables if table['weaponClass'] in classes), None)
    universal = next((table for table in tables if table['weaponClass'] == 'Universal'), None)
    rules = [row for row in rows('damage.json', 'rules') if row['entity'] == 'Infantry']
    weapon_tags = list(classes)
    # Resolve exported bespoke weapon tags only by exact normalized ID/name suffix.
    normalize = lambda text: re.sub(r'[^a-z0-9]', '', text.casefold())
    aliases = {normalize(item['id'].split('.')[-1]), normalize(item.get('name', ''))} - {''}
    for rule in rules:
        for tag in rule.get('source', []):
            if tag.startswith('Weapon.') and normalize(tag.split('.')[-1]) in aliases and tag not in weapon_tags:
                weapon_tags.append(tag)
    return {'ammo': ammo, 'weapon': weapon, 'weaponTags': weapon_tags,
            'universal': universal.get('multipliers', {}) if universal else {},
            'multipliers': class_table.get('multipliers', {}) if class_table else {},
            'weaponClass': class_table['weaponClass'] if class_table else None,
            'armor': [{'id': row['id'], 'name': row.get('name', row['id']), 'slot': row['slot'],
                       'context': row.get('damageContext'), 'coveredLocations': row.get('coveredLocations', []),
                       'reduction': row['stages'][0]['damageReduction']}
                      for row in rows('equipment.json', 'armor') if row.get('stages')],
            'ammoTypes': rows('damage.json', 'ammoTypes'), 'rules': rules}
