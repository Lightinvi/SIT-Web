/** Same-origin invitation settings and attributed click requests. */
export type Invitation = {
  role: string
  description: string
  isExpired: boolean
  requiresCode: boolean
}

/** Load current database settings and a browser-bound token for recording clicks. */
export async function getInvitations(signal: AbortSignal): Promise<{ invitations: Invitation[]; csrf_token: string }> {
  const response = await fetch('/api/invitations', { signal, cache: 'no-store' })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || '無法載入邀請，請稍後再試。')
  if (!Array.isArray(data.invitations) || typeof data.csrf_token !== 'string' ||
      !data.invitations.every((item: Invitation) => item && typeof item.role === 'string' &&
        typeof item.description === 'string' && typeof item.isExpired === 'boolean' &&
        typeof item.requiresCode === 'boolean')) throw new Error('邀請資料格式不正確。')
  return data
}

/** Record a click before navigation; the returned URL is restricted to Discord invites. */
export async function requestInvitation(role: string, administratorCode: string, requestId: string, csrf: string, signal: AbortSignal): Promise<string> {
  const response = await fetch('/api/invitations/click', {
    method: 'POST', signal, headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
    body: JSON.stringify({ role, administrator_code: administratorCode, request_id: requestId }),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.error || '暫時無法開啟邀請，請稍後再試。')
  if (typeof data.url !== 'string' || !/^https:\/\/discord\.com\/invite\/[A-Za-z0-9_-]{2,100}$/.test(data.url)) {
    throw new Error('邀請網址格式不正確。')
  }
  return data.url
}
