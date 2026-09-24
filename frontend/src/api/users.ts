import type { UsersResponse } from '../types/user'

export async function getUsers(signal?: AbortSignal): Promise<UsersResponse> {
  const response = await fetch('/api/users', { signal, cache: 'no-store' })
  if (!response.ok) throw new Error('無法取得使用者資料，請稍後重試。')
  const data: unknown = await response.json()
  if (
    typeof data !== 'object' || data === null || !('users' in data) ||
    !Array.isArray(data.users) ||
    !data.users.every((user: unknown) =>
      typeof user === 'object' && user !== null &&
      'id' in user && typeof user.id === 'number' &&
      'name' in user && typeof user.name === 'string' &&
      'email' in user && typeof user.email === 'string' &&
      'role' in user && typeof user.role === 'string' &&
      'status' in user && (user.status === 'active' || user.status === 'invited'))
  ) throw new Error('收到的使用者資料格式不正確。')
  return data as UsersResponse
}
