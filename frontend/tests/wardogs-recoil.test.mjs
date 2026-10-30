import { test } from 'node:test'
import assert from 'node:assert/strict'
import { recoilPath } from '../src/utils/wardogsRecoil.ts'

test('recoil adds each shot including downward and sideways corrections', () => {
  assert.deepEqual(recoilPath([{ x: 1, y: 2 }, { x: -2, y: -0.5 }]), [{ x: 0, y: 0 }, { x: 1, y: 2 }, { x: -1, y: 1.5 }])
  assert.deepEqual(recoilPath([]), [{ x: 0, y: 0 }])
  assert.deepEqual(recoilPath([{ x: NaN, y: 1 }]), [])
})
