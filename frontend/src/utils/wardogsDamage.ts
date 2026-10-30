export type Projectile = { damage?: number; damageType?: string; damageContext?: string[]; explosive?: unknown }
export type Ammo = { id: string; name: string; icon?: string; ammoType: string; projectile?: Projectile | null }
export type Armor = { id: string; name: string; slot: string; context?: string; coveredLocations: string[]; reduction: number }
type Rule = { source: string[]; target: string[]; instigator: string[]; hitLocations: string[]; alignment?: string; category: string; operation: string; amount: number; custom?: string }
export type DamageModel = { ammo: Ammo[]; weapon: { rpm?: number; fireModes?: string[]; damageFalloff?: { distance: number; multiplier: number; interpolation?: string }[] }; weaponTags: string[]; weaponClass: string | null; universal: Record<string, number>; multipliers: Record<string, number>; armor: Armor[]; ammoTypes: { ammoType: string; modifier: number; byArmsClass: Record<string, number> }[]; rules: Rule[] }
export const HIT_ZONES = [['Head', '頭部'], ['Neck', '頸部'], ['Torso.Upper', '上胸'], ['Torso.Middle', '中胸'], ['Torso.Lower', '腹部'], ['Pelvis', '骨盆'], ['Arm.Upper', '上臂'], ['Arm.Lower', '前臂'], ['Arm.Hand', '手部'], ['Leg.Thigh', '大腿'], ['Leg.Calf', '小腿'], ['Leg.Foot', '腳部']] as const
export function falloffAt(points: DamageModel['weapon']['damageFalloff'], range: number) {
  if (!points?.length) return null
  const sorted = [...points].sort((a, b) => a.distance - b.distance)
  if (range <= sorted[0].distance) return sorted[0].multiplier
  for (let i = 1; i < sorted.length; i++) {
    if (range <= sorted[i].distance) {
      const previous = sorted[i - 1], next = sorted[i]
      if (previous.interpolation === 'Constant') return range === next.distance ? next.multiplier : previous.multiplier
      return previous.multiplier + (next.multiplier - previous.multiplier) * (range - previous.distance) / (next.distance - previous.distance)
    }
  }
  return sorted[sorted.length - 1].multiplier
}
function matches(tag: string, actual: string[]) { return actual.some(value => value.toLowerCase() === tag.toLowerCase() || value.toLowerCase().startsWith(tag.toLowerCase() + '.')) }
export function simulateHit(model: DamageModel, ammo: Ammo, zone: string, range: number, helmet?: Armor, body?: Armor, hp = 100) {
  const projectile = ammo.projectile
  const falloff = falloffAt(model.weapon.damageFalloff, range)
  const universal = model.universal[zone], weaponMultiplier = model.multipliers[zone]
  // Explosive splash and pellet counts require a separate impact model.
  if (!projectile || typeof projectile.damage !== 'number' || !projectile.damageType?.includes('.Bullet.') || projectile.explosive || falloff === null || universal === undefined || weaponMultiplier === undefined) return null
  const armor = [helmet, body].find(piece => piece?.coveredLocations.includes(zone))
  const source = [projectile.damageType.replace(/^Meta\.Damage\./, ''), ...model.weaponTags, `AmmoModifier.${ammo.ammoType}`, ...(projectile.damageContext ?? []).map(tag => tag.replace(/^Meta\.Damage\./, ''))]
  const target = armor?.context ? [armor.context] : []
  const location = ['Infantry.' + zone]
  const matched = model.rules.filter(rule => !rule.custom && !rule.alignment && !rule.instigator.length && rule.operation === 'Percentage_Ongoing' && rule.source.every(tag => matches(tag, source)) && rule.target.every(tag => matches(tag, target)) && (!rule.hitLocations.length || rule.hitLocations.some(tag => matches(tag, location))))
  const plain = matched.reduce((factor, rule) => factor * (1 + rule.amount / 100), 1)
  const ammoType = model.ammoTypes.find(row => row.ammoType.toLowerCase() === ammo.ammoType.toLowerCase())
  const arms = source.find(tag => tag.startsWith('Arms.'))?.slice(5)
  const effectiveness = ammoType ? (arms ? ammoType.byArmsClass[arms] ?? ammoType.modifier : ammoType.modifier) : 1
  const protection = armor ? 1 - armor.reduction * effectiveness / 100 : 1
  const raw = projectile.damage * universal * weaponMultiplier * falloff
  const effective = Math.max(0, raw * plain * protection)
  const shots = effective > 0 ? Math.ceil(hp / effective) : null
  const ttk = shots !== null && model.weapon.rpm && model.weapon.rpm > 0 ? (shots - 1) * 60 / model.weapon.rpm : null
  return { base: projectile.damage, multiplier: universal * weaponMultiplier, falloff, raw, effective, shots, ttk, armor, plain, protection }
}
