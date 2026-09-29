/** Verify signed ledger presentation and protected API request/error handling. */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { shardRequest, signedAmount } from '../src/api/shards.ts'

test('ledger changes display explicit positive and negative signs', () => {
  assert.equal(signedAmount(1200), '+1,200')
  assert.equal(signedAmount(-30), '-30')
})

test('transfer requests retain CSRF, payload, and an abort signal', async t => {
  let captured
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    captured = { url, options }
    return new Response(JSON.stringify({ balance: 70 }), { status: 200 })
  })
  const result = await shardRequest('/transfer', { method: 'POST', headers: { 'X-CSRF-Token': 'token' }, body: '{"amount":30}' })
  assert.equal(result.balance, 70)
  assert.equal(captured.url, '/api/star-shards/transfer')
  assert.equal(captured.options.cache, 'no-store')
  assert.equal(captured.options.headers['X-CSRF-Token'], 'token')
  assert(captured.options.signal instanceof AbortSignal)
})

test('server rejection is never mistaken for a successful transfer', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ error: 'Insufficient balance' }), { status: 400 }))
  await assert.rejects(shardRequest('/transfer'), /Insufficient balance/)
})
