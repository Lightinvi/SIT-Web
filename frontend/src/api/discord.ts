/** Fetch guild resources and derive the public administrator display list. */
const guildId = '510386488639488001'

// Match exact Discord role names or IDs; multiple entries use OR matching.
const administratorRoles = ['513295891482804250']

/** Discord guild membership fields needed for role filtering and avatar selection. */
type Member = {
  nick?: string | null
  avatar?: string | null
  roles: string[]
  user: { id: string; username: string; global_name?: string | null; avatar?: string | null; bot?: boolean; discriminator?: string }
}
/** Discord role identity and ordering used to select a member's displayed role. */
type Role = { id: string; name: string; permissions: string; position: number }
/** Public administrator identity consumed by the homepage carousel. */
export type Administrator = { id: string; name: string; username: string; avatar: string; role: string }

/**
 * Select non-bot members matching any configured role ID or exact role name.
 * Use the highest-position matching role and prefer guild-specific names/avatars.
 * Return identities sorted by display name using the Traditional Chinese locale.
 */
export function selectAdministrators(members: Member[], roles: Role[], roleIdentifiers: string[]): Administrator[] {
  const adminRoles = roles.filter(role => roleIdentifiers.includes(role.id) || roleIdentifiers.includes(role.name))
    .sort((a, b) => b.position - a.position)
  return members.filter(member => !member.user.bot && adminRoles.some(role =>
    role.id === guildId || member.roles.includes(role.id)))
    .map(member => {
      const user = member.user
      const defaultIndex = user.discriminator && user.discriminator !== '0'
        ? Number(user.discriminator) % 5 : Number((BigInt(user.id) >> 22n) % 6n)
      const avatar = member.avatar
        ? `https://cdn.discordapp.com/guilds/${guildId}/users/${user.id}/avatars/${member.avatar}.png?size=256`
        : user.avatar ? `https://cdn.discordapp.com/avatars/${user.id}/${user.avatar}.png?size=256`
          : `https://cdn.discordapp.com/embed/avatars/${defaultIndex}.png`
      return { id: user.id, name: member.nick || user.global_name || user.username,
        username: user.username, avatar,
        role: adminRoles.find(role => role.id === guildId || member.roles.includes(role.id))!.name }
    }).sort((a, b) => a.name.localeCompare(b.name, 'zh-Hant'))
}

/**
 * Fetch members and roles concurrently through the backend's Discord cache.
 * @param signal Shared cancellation signal for both requests.
 * @throws When either request fails or the collection envelopes are invalid.
 */
export async function getAdministrators(signal: AbortSignal): Promise<Administrator[]> {
  const [membersResponse, rolesResponse] = await Promise.all([
    fetch('/api/discord/members', { signal }), fetch('/api/discord/roles', { signal }),
  ])
  if (!membersResponse.ok || !rolesResponse.ok) throw new Error('暫時無法載入管理員，請稍後再試。')
  const [members, roles] = await Promise.all([membersResponse.json(), rolesResponse.json()])
  if (!Array.isArray(members.members) || !Array.isArray(roles.roles)) throw new Error('管理員資料格式不正確。')
  return selectAdministrators(members.members, roles.roles, administratorRoles)
}
