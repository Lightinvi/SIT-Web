/** Verify daily spinner requests preserve CSRF and retry identity without choosing prizes. */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spinnerRequest } from '../src/api/spinner.ts'

test('status requests bypass caches and expose published server odds', async t => {
  const prizes = [{ multiplier: 0.5, probability: 8, reward: 5 }]
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/daily-spinner')
    assert.equal(options.cache, 'no-store')
    assert(options.signal instanceof AbortSignal)
    return new Response(JSON.stringify({ prizes, canSpin: true }))
  })
  assert.deepEqual((await spinnerRequest()).prizes, prizes)
})

test('draw sends the same request ID and CSRF header without prize fields', async t => {
  const body = JSON.stringify({ requestId: '11111111-1111-4111-8111-111111111111' })
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/daily-spinner/spin')
    assert.equal(options.headers['X-CSRF-Token'], 'token')
    assert.equal(options.body, body)
    return new Response(JSON.stringify({ awarded: false, result: { reward: 10 } }))
  })
  const options = { method: 'POST', headers: { 'X-CSRF-Token': 'token' }, body }
  assert.equal((await spinnerRequest('/spin', options)).awarded, false)
  assert.equal((await spinnerRequest('/spin', options)).result.reward, 10)
})

test('rejected draws surface server errors without fabricating a reward', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ error: '請先登入帳號。' }), { status: 401 }))
  await assert.rejects(spinnerRequest('/spin'), /請先登入帳號/)
})
