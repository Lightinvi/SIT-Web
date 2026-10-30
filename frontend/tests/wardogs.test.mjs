import { test } from 'node:test'
import assert from 'node:assert/strict'
import { WARDOGS_CATEGORIES, wardogsCategory } from '../src/utils/wardogsCategories.ts'

test('categories use the requested fixed order', () => {
  assert.deepEqual(WARDOGS_CATEGORIES, ['武器', '配件', '彈藥', '裝備', '背包(容器)', '物品', '投擲物', '部署道具', '建築', '載具', '載具武器', '其他'])
})

test('semantic rules resolve conflicting tags and source labels', () => {
  const examples = [
    [{ id: 'Id.Item.SV98Stock', subtitle: 'Ammunition', tags: ['Item.Attachment.Stock'] }, '其他'],
    [{ id: 'Id.Item.SKSExtendedMag', subtitle: 'Ammunition', tags: ['Item.Attachment.Magazine'] }, '配件'],
    [{ id: 'ID.Item.RepairTool.Drill.Heavy', tags: ['Item.Weapon'] }, '物品'],
    [{ id: 'Id.Item.VehicleTurretHeavy', tags: ['Inventory.Slot.Vehicle.Weapon.TNK_01.Turret', 'Item.Weapon'] }, '載具武器'],
    [{ id: 'ID.Item.SmokeGrenade.Green', subtitle: 'Logistics // Quick Slot' }, '投擲物'],
    [{ id: 'Id.Item.Claymore' }, '部署道具'],
    [{ id: 'Id.Item.FOB', asset: 'Plugins/GameFeatures/Items/Buildables/Content/Data/ForwardOperatingBase/ID_ForwardOperatingBase' }, '部署道具'],
    [{ id: 'Id.Item.BuildToolSupply', asset: 'Plugins/GameFeatures/Items/Buildables/Content/Data/BuildToolSupply/ID_BuildToolSupply' }, '建築'],
    [{ id: 'Id.Item.SupplyCrate', tags: ['Inventory.Type.Storage'] }, '背包(容器)'],
    [{ id: 'Id.Item.Round', tags: ['Item.Ammo'] }, '彈藥'],
    [{ id: 'Id.Item.Rifle', tags: ['Item.Weapon'] }, '武器'],
    [{ id: 'Vehicle.Variant.Land.Tracked.Tank', kind: 'vehicle' }, '載具'],
    [{ id: 'Buildable.Wall' }, '建築'],
    [{ id: 'Unknown.Item', subtitle: 'Assault Rifle' }, '其他'],
  ]
  for (const [item, expected] of examples) assert.equal(wardogsCategory(item), expected, item.id)
})


test('unfinished names and excluded attachment parts go to other', () => {
  for (const name of ['Id.Item.M249Stock', 'WEPN_031 Bizon Standard Barrel', 'ID.Item.OPT_Unknown', 'AK74 Barrel', 'Wooden Pistol Grip', 'Polymer Stock', 'Zenit Handguard', 'AK Dust Cover', 'Match Trigger']) {
    assert.equal(wardogsCategory({ id: 'Id.Item.Test', name, tags: ['Item.Attachment'] }), '其他', name)
  }
  for (const part of ['Barrel', 'Grip', 'Stock', 'Handguard', 'Pistolgrip']) {
    assert.equal(wardogsCategory({ id: 'Id.Item.Test', name: 'Named part', tags: [`Item.Attachment.${part}.M4`] }), '其他', part)
  }
  for (const name of ['6-10x Scope MOA', 'STANAG 30 RND Magazine', 'PBS-4 Suppressor']) {
    assert.equal(wardogsCategory({ id: 'Id.Item.Test', name, tags: ['Item.Attachment'] }), '配件', name)
  }
  assert.equal(wardogsCategory({ id: 'Id.Item.Unknown', name: 'Id.Item.Unknown', tags: ['Item.Ammo'] }), '彈藥')
})


test('support attachments stay in attachments while dust covers and triggers do not', () => {
  for (const [name, tag] of [['Tactical Foregrip', 'Underbarrel'], ['Harris Bipod', 'Bipod.Attached'], ['Grip Pod', 'Grip']]) {
    assert.equal(wardogsCategory({ id: 'Id.Item.Test', name, tags: [`Item.Attachment.${tag}`] }), '配件', name)
  }
  for (const tag of ['DustCover', 'Trigger']) {
    assert.equal(wardogsCategory({ id: 'Id.Item.Test', name: 'Named part', tags: [`Item.Attachment.${tag}`] }), '其他')
  }
  assert.equal(wardogsCategory({ id: 'Id.Item.Test', name: 'Id.Item.Bipod', tags: ['Item.Attachment.Bipod'] }), '其他')
})


test('IEDs, protective equipment, supplies and cards follow the revised categories', () => {
  const examples = [
    [{ id: 'Id.Item.IED.Explosive', name: 'Improvised Explosive Device', tags: ['Item.Ammo'] }, '部署道具'],
    [{ id: 'Id.Item.IED.Trigger', name: 'Improvised Explosive Device', tags: ['Item.Resource.Ammo'] }, '部署道具'],
    [{ id: 'Id.Item.HeavyHelmet', tags: ['Inventory.Slot.Helmet'] }, '裝備'],
    [{ id: 'Id.Item.HeavyArmor', tags: ['Inventory.Slot.Armor'] }, '裝備'],
    [{ id: 'Id.Item.GhillieArmor' }, '裝備'],
    [{ id: 'Id.Item.LargeTacVest', tags: ['Inventory.Slot.Vest'] }, '物品'],
    [{ id: 'Id.Item.Parachute', tags: ['Inventory.Slot.Traversal'] }, '物品'],
    [{ id: 'Id.Item.Binoculars' }, '物品'],
    [{ id: 'Id.Item.FuelSupplies' }, '建築'],
    [{ id: 'Id.Item.SparePartsSupplies' }, '建築'],
    [{ id: 'Id.Item.KeyCard.Alpha.1', name: 'Alpha Card 1' }, '其他'],
    [{ id: 'Id.Item.VehicleSupplyCrate.Large', tags: ['Inventory.Slot.SupplyContainer'] }, '背包(容器)'],
  ]
  for (const [item, category] of examples) assert.equal(wardogsCategory(item), category, item.id)
})


test('defibrillator is a medical item even when tagged as a weapon', () => {
  assert.equal(wardogsCategory({ id: 'Id.Item.Defibrillator.Standard', name: 'Defibrillator', tags: ['Item.Weapon', 'Inventory.Slot.Specialist'] }), '物品')
})
