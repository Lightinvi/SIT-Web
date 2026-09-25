import { test } from 'node:test'
import assert from 'node:assert/strict'
import { selectAdministrators } from '../src/api/discord.ts'

const roles = [
  { id: '1', name: '社群管理員', permissions: '0', position: 2 },
  { id: '2', name: '其他', permissions: '8', position: 1 },
]
const member = (id, assigned, extra = {}) => ({ roles: assigned, user: { id, username: `user${id}`, ...extra } })

test('matches exact role name or ID, excludes bots and unrelated administrators', () => {
  const members = [member('100', ['1']), member('101', ['1'], { bot: true }), member('102', ['2'])]
  assert.deepEqual(selectAdministrators(members, roles, ['社群管理員']).map(m => m.id), ['100'])
  assert.deepEqual(selectAdministrators(members, roles, ['1']).map(m => m.id), ['100'])
  assert.deepEqual(selectAdministrators(members, roles, []), [])
})

test('multiple matching roles do not duplicate members', () => {
  const result = selectAdministrators([member('100', ['1', '2'])], roles, ['1', '2'])
  assert.equal(result.length, 1)
  assert.equal(result[0].role, '社群管理員')
})

test('nickname and guild avatar take precedence with user and default fallbacks', () => {
  const source = member('100', ['1'], { global_name: '顯示名稱', avatar: 'global' })
  const [guild] = selectAdministrators([{ ...source, nick: '群組暱稱', avatar: 'guild' }], roles, ['1'])
  assert.equal(guild.name, '群組暱稱')
  assert.match(guild.avatar, /guilds\/510386488639488001\/users\/100\/avatars\/guild/)
  const [global] = selectAdministrators([source], roles, ['1'])
  assert.equal(global.name, '顯示名稱')
  assert.match(global.avatar, /avatars\/100\/global/)
  const [fallback] = selectAdministrators([member('100', ['1'])], roles, ['1'])
  assert.equal(fallback.name, 'user100')
  assert.match(fallback.avatar, /embed\/avatars\/0.png/)
})
