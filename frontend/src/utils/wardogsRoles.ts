/** Localized display names; preserve the source role identifiers for data joins. */
const roleNames: Record<string, string> = {
  infantry: '突擊兵',
  recon: '偵查兵',
  medic: '醫療兵',
  support: '支援兵',
  pilot: '飛行員',
  driver: '駕駛員',
  wardog: '生涯',
}

export function wardogsRoleName(role?: string): string {
  return role ? roleNames[role.trim().toLowerCase()] ?? role : '未提供'
}
