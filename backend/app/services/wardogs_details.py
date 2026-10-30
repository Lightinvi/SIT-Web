"""Join original datasets through exact case-insensitive IDs and explicit references."""
import copy
from functools import lru_cache
import json
from pathlib import Path

TITLES = {'weapons': '武器數值', 'projectiles': '彈藥與彈道', 'attachments': '配件效果', 'armor': '護甲效果', 'vehicles': '載具數值', 'configs': '載具設定', 'cosmetics': '外觀', 'tables': '掉落來源', 'rules': '傷害規則', 'vehicleSeats': '載具座位防護', 'goldMarket': '金條商店', 'roles': '職業等級', 'ammoTypes': '彈種傷害修正'}


@lru_cache(maxsize=2)
def load_sources(root, signature):
    """Cache immutable parsed source snapshots; file signatures invalidate local edits."""
    sources = {}
    for filename, _, _ in signature:
        if filename.startswith('schema/') or filename == 'MANIFEST.json':
            continue
        sources[filename] = json.loads((Path(root) / filename).read_text())
    return sources


def references(value, identifiers):
    if isinstance(value, str):
        return value.casefold() in identifiers
    if isinstance(value, list):
        return any(references(child, identifiers) for child in value)
    if isinstance(value, dict):
        return any(references(child, identifiers) for child in value.values())
    return False


def without_durability(value):
    if isinstance(value, dict):
        return {key: without_durability(child) for key, child in value.items() if key != 'durability'}
    if isinstance(value, list):
        return [without_durability(child) for child in value]
    return value


def item_details(root, item_id):
    root = Path(root)
    signature = tuple((path.relative_to(root).as_posix(), path.stat().st_mtime_ns, path.stat().st_size)
                      for path in sorted(root.rglob('*.json')))
    sources = load_sources(str(root), signature)
    base = sources['items.json']
    item = next((row for row in base['items'] if row['id'].casefold() == item_id.casefold()), None)
    if item is None:
        return None
    item = copy.deepcopy(item)
    identity = {item['id'].casefold()}
    sections = []
    checked = []
    contexts = set()
    for filename, source in sources.items():
        if filename == 'items.json' or not isinstance(source, dict):
            continue
        if source.get('gameBuild') != base['gameBuild']:
            continue  # Never merge statistics from another build.
        checked.append(filename)
        identifiers = identity
        if filename == 'ammo.json':
            identifiers = identity | {tag.casefold() for tag in item.get('tags', []) if tag.casefold().startswith('item.caliber.')}
        for collection, rows in source.items():
            if not isinstance(rows, list):
                continue
            matches = [row for row in rows if isinstance(row, dict) and references(row, identifiers)]
            if not matches:
                continue
            sections.append({'source': filename, 'collection': collection,
                             'title': TITLES.get(collection, collection), 'records': without_durability(matches)})
            for row in matches:
                if str(row.get('id', '')).casefold() in identity:
                    for key in ('name', 'description', 'icon', 'weight', 'maxStack', 'grid', 'unlock'):
                        if item.get(key) in (None, '') and row.get(key) is not None:
                            item[key] = copy.deepcopy(row[key])
                    contexts.update(str(row[key]).casefold() for key in ('damageContext', 'damageEntity') if row.get(key))
    damage = sources.get('damage.json', {})
    if contexts and damage.get('gameBuild') == base['gameBuild']:
        entities = contexts | {context.split('.')[0] for context in contexts}
        rows = [row for row in damage.get('rules', []) if str(row.get('entity', '')).casefold() in entities]
        if rows:
            sections.append({'source': 'damage.json', 'collection': 'rules', 'title': '傷害規則', 'records': rows})
    if damage.get('gameBuild') == base['gameBuild']:
        ammo_types = {tag[len('Item.Ammo.Type.'):].casefold() for tag in item.get('tags', []) if tag.casefold().startswith('item.ammo.type.')}
        rows = [row for row in damage.get('ammoTypes', []) if str(row.get('ammoType', '')).casefold() in ammo_types]
        if rows:
            sections.append({'source': 'damage.json', 'collection': 'ammoTypes', 'title': '彈種傷害修正', 'records': rows})
    role = (item.get('unlock') or {}).get('role')
    roles = sources.get('roles.json', {})
    if role and roles.get('gameBuild') == base['gameBuild']:
        rows = [row for row in roles.get('roles', []) if str(row.get('id', '')).casefold() == str(role).casefold()]
        if rows:
            sections.append({'source': 'roles.json', 'collection': 'roles', 'title': '解鎖職業等級', 'records': rows})
    # Vendor entries may live under a related base item; match the actual offered tag.
    offers = [offer for row in base['items'] for offer in row.get('vendor', [])
              if str(offer.get('tag', '')).casefold() in identity]
    item['vendor'] = list({json.dumps(offer, sort_keys=True): offer for offer in offers}.values())
    from app.services.wardogs_prices import fallback_price
    price_source = None
    if not any(isinstance(offer.get('price'), (int, float)) for offer in offers):
        price_source = fallback_price(base['gameBuild'], item['id'])
        if price_source:
            item['vendor'] = [{'tag': item['id'], 'price': price_source['price'], 'amount': 1}]
    from app.services.wardogs_simulation import simulation_data
    weapon_source = sources.get('weapons.json', {})
    weapon = next((row for row in weapon_source.get('weapons', []) if row['id'].casefold() in identity), None) if weapon_source.get('gameBuild') == base['gameBuild'] else None
    simulation = simulation_data(sources, item, weapon) if weapon else None
    ammo_details = None
    item_tags = {tag.casefold() for tag in item.get('tags', [])}
    if 'item.ammo' in item_tags:
        ammo_source = sources.get('ammo.json', {})
        projectiles = ammo_source.get('projectiles', []) if ammo_source.get('gameBuild') == base['gameBuild'] else []
        projectile = next((row for row in projectiles if any(identifier.casefold() in identity for identifier in row.get('items', []))), None)
        if projectile is None:
            projectile = next((row for row in projectiles if row['id'].casefold() in item_tags), None)
        catalog_ids = {row['id'].casefold() for row in base['items']}
        compatible = [row for row in weapon_source.get('weapons', [])
                      if row['id'].casefold() in catalog_ids and
                      any('item.caliber.' + caliber.casefold() in item_tags for caliber in row.get('calibers', []))] if weapon_source.get('gameBuild') == base['gameBuild'] else []
        ammo_details = {'damage': projectile.get('damage') if projectile else None,
                        'projectileId': projectile.get('id') if projectile else None,
                        'weapons': [{'id': row['id'], 'name': row.get('name') or next(item.get('name', item['id']) for item in base['items'] if item['id'].casefold() == row['id'].casefold())} for row in compatible]}
    return {'priceSource': price_source, 'ammoDetails': ammo_details, 'simulation': simulation, 'item': without_durability(item), 'sections': sections, 'checkedSources': checked, 'gameBuild': base['gameBuild']}
