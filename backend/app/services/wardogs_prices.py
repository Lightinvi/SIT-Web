"""Sourced fallback prices for vendor entries absent from the extracted build."""
SOURCE = 'https://store.steampowered.com/news/app/1867240/view/1846651706674560'
# Official Season 02 vendor prices (2026-10-14). Do not carry them into unverified builds.
PRICES_BY_BUILD = {
    '25937608': {
        'id.item.ak74m': 800,
        'id.item.cgm4': 2400,
        'id.item.tar21': 1200,
        'id.item.vector': 5600,
        'id.item.wepn_032': 1000,
        'id.item.mmgl': 7500,
    },
}


def fallback_price(build, item_id):
    price = PRICES_BY_BUILD.get(build, {}).get(item_id.casefold())
    if price is None:
        return None
    return {'price': price, 'source': SOURCE, 'label': '官方 Season 02 公告', 'publishedAt': '2026-10-14'}
