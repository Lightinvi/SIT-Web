/** Site-owned categories. Prefer semantic tags and asset paths over source subtitles. */
export const WARDOGS_CATEGORIES = ['武器', '配件', '彈藥', '裝備', '背包(容器)', '物品', '投擲物', '部署道具', '建築', '載具', '載具武器', '其他'] as const
export type WardogsCategory = typeof WARDOGS_CATEGORIES[number]
export type CategorizedItem = { id: string; name?: string; kind?: string; asset?: string; tags?: string[] }

export function wardogsCategory(item: CategorizedItem): WardogsCategory {
  const tags = (item.tags ?? []).map(tag => tag.toLowerCase())
  const has = (prefix: string) => tags.some(tag => tag === prefix || tag.startsWith(`${prefix}.`))
  const identity = `${item.id} ${item.asset ?? ''}`.toLowerCase()
  if (has('inventory.slot.vehicle.weapon')) return '載具武器'
  if (item.kind?.toLowerCase() === 'vehicle' || item.id.toLowerCase().startsWith('vehicle.')) return '載具'
  if (has('inventory.slot.backpack') || has('inventory.slot.supplycontainer') || has('inventory.slot.vehicle.storage') || has('inventory.type.storage') || /backpack|supplycrate|vehiclestorage|\/storage\//.test(identity)) return '背包(容器)'
  if (/\.ied(?:\.|\s|$)|\/ied\//.test(identity) || /improvised explosive device/i.test(item.name ?? '')) return '部署道具'
  if (/keycard/.test(identity) || /\bcards?\b/i.test(item.name ?? '')) return '其他'
  if (/atmine|at_mine|claymore|ammocrate|\/placeables\/|\.fob\b|forwardoperatingbase/.test(identity)) return '部署道具'
  if (has('item.archetype.grenade') || /grenade|molotov|\/throwable\//.test(identity)) return '投擲物'
  if (has('item.attachment') || /\/attachments\/|\.sght_/.test(identity)) {
    const name = item.name?.trim() ?? ''
    const internalName = /^(?:id[._]item(?:[._]|$)|(?:wepn|brl|grp|pgrp|stok|hgd|sght|muzl|trgr)_\d+\b)/i.test(name)
    if (internalName) return '其他'
    const partIdentity = `${name} ${identity}`
    if (/dust[ _-]?cover|trigger/i.test(partIdentity) || has('item.attachment.dustcover') || has('item.attachment.trigger')) return '其他'
    if (/fore[ _-]?grip|bipod|grip[ _-]?pod/i.test(partIdentity) || has('item.attachment.bipod') || has('item.attachment.underbarrel')) return '配件'
    const excludedPart = /barrel|grip|stock|handguard/i.test(`${name} ${identity}`) ||
      tags.some(tag => /^item\.attachment\.(?:barrel|grip|pistolgrip|stock|handguard)(?:\.|$)/.test(tag))
    return excludedPart ? '其他' : '配件'
  }
  if (has('item.ammo') || has('item.resource.ammo')) return '彈藥'
  // Only helmets, armor and ghillie clothing remain equipment; tools are ordinary items.
  if (has('inventory.slot.armor') || has('inventory.slot.helmet') || /\/armor\/|ghillie|helmet/.test(identity)) return '裝備'
  if (has('inventory.slot.vest') || has('inventory.slot.traversal') || /defibrillator|buildtool\.hammer|repairtool|vehiclerepairtool|crowbar|binocular|monocular|rangefinder|medkit|\/enox\/|resuscitator|\/clothing\/vests\//.test(identity)) return '物品'
  if (has('item.weapon') || ['ar', 'smg', 'lmg', 'dmr', 'sniper', 'pistol', 'shotgun', 'launcher', 'bow'].some(type => has(`item.archetype.${type}`)) || /\/weapons\/fists\//.test(identity)) return '武器'
  if (/\/buildables\/|\/buildings\/|^buildable\.|^building\./.test(identity) || /suppl/.test(identity)) return '建築'
  if (/suppl|fuelcan|bandage|stimpen|musictape|\/consumables\/|\.flares\b/.test(identity)) return '物品'
  return '其他'
}
