import { test } from 'node:test'
import assert from 'node:assert/strict'
import { falloffAt, simulateHit } from '../src/utils/wardogsDamage.ts'
const model = {
  weapon: { rpm: 600, damageFalloff: [{ distance: 0, multiplier: 1 }, { distance: 100, multiplier: 0.5 }] },
  weaponTags: ['Weapon.AR'], universal: { Head: 1, 'Torso.Upper': 1.1 }, multipliers: { Head: 2.35, 'Torso.Upper': 0.885 },
  ammoTypes: [{ ammoType: 'ArmorPiercing', modifier: 0.3, byArmsClass: { Medium: 0.6 } }],
  rules: [{ source: ['Bullet', 'AmmoModifier.ArmorPiercing'], target: [], instigator: [], hitLocations: [], category: 'AmmoModifier', operation: 'Percentage_Ongoing', amount: -20 }],
}
const ammo = { id: 'round', name: 'Round', ammoType: 'FMJ', projectile: { damage: 28, damageType: 'Meta.Damage.Bullet.556mm', damageContext: ['Meta.Damage.Arms.Medium'] } }
const helmet = { id: 'helmet', name: 'L1', context: 'Helmet.Light', reduction: 30, coveredLocations: ['Head'] }

test('unarmored hit uses both bone tables; TTK excludes time before the first hit', () => {
  const result = simulateHit(model, ammo, 'Head', 0)
  assert.equal(result.effective, 65.8)
  assert.equal(result.shots, 2)
  assert.equal(result.ttk, 0.1)
})
test('coverage and AP arms overrides determine armor mitigation', () => {
  assert.equal(simulateHit(model, ammo, 'Head', 0, helmet).effective, 65.8 * 0.7)
  assert.equal(simulateHit(model, ammo, 'Torso.Upper', 0, helmet).armor, undefined)
  const result = simulateHit(model, { ...ammo, ammoType: 'ArmorPiercing' }, 'Head', 0, helmet)
  assert.ok(Math.abs(result.effective - 65.8 * 0.8 * 0.82) < 1e-10)
})
test('falloff interpolation and unsupported inputs do not produce invented results', () => {
  assert.equal(falloffAt(model.weapon.damageFalloff, 50), 0.75)
  assert.equal(falloffAt([{ distance: 0, multiplier: 1, interpolation: 'Constant' }, { distance: 100, multiplier: 0.5 }], 50), 1)
  assert.equal(simulateHit(model, { ...ammo, projectile: { damage: 100, damageType: 'Meta.Damage.Explosive.Rocket' } }, 'Head', 0), null)
  assert.equal(simulateHit(model, ammo, 'Missing', 0), null)
  assert.equal(simulateHit({ ...model, weapon: { rpm: 600 } }, ammo, 'Head', 0), null)
})
