/** Daily spinner configuration and receipts issued exclusively by the server. */
export type SpinnerPrize = { multiplier: number; probability: number; reward: number }
export type SpinnerReceipt = { id: string; userId: string; spinDate: string; multiplier: number; baseReward: number; reward: number; createdAt: number }
export type SpinnerState = { authenticated: boolean; userId?: string; csrfToken?: string; day: string; serverTime: number; nextResetAt: number; timezone: string; baseReward: number; prizes: SpinnerPrize[]; todaySpin: SpinnerReceipt | null; canSpin: boolean }
export type SpinResponse = SpinnerState & { result: SpinnerReceipt; awarded: boolean }

/** Fetch fresh eligibility or atomically request a reward using the existing login cookie. */
export async function spinnerRequest<T>(path = '', options: RequestInit = {}): Promise<T> {
  const timeout = AbortSignal.timeout(15000)
  const response = await fetch(`/api/daily-spinner${path}`, { ...options, cache: 'no-store',
    signal: options.signal ? AbortSignal.any([options.signal, timeout]) : timeout })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || '暫時無法載入轉盤。')
  return data as T
}
