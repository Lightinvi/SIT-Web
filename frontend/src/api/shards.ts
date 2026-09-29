/** Typed private Star Shard endpoints; balances are integer units. */
export type ShardMember = { userId: string; username: string | null; displayName: string | null }
export type ShardRecord = { id: string; userId: string; amount: number; beforeBlance: number; afterBlance: number; transactionType: string; transactionSource: string; description: string; createdAt: number }
export type ShardPage = { records: ShardRecord[]; nextCursor: string | null }

/** Fetch private JSON with a bounded wait and retain server validation messages. */
export async function shardRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/star-shards${path}`, { cache: 'no-store', ...options,
    signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(15000)]) : AbortSignal.timeout(15000) })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || '暫時無法處理，請稍後重試。')
  return data as T
}

/** Format signed changes while preserving a visible plus sign for income. */
export const signedAmount = (amount: number) => `${amount > 0 ? '+' : ''}${amount.toLocaleString('zh-TW')}`
