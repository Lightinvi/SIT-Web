"""Central mapping of verified Discord roles, ordered from highest to lowest."""

ACCESS_ROLES = (
    {'id': '1555051124334137468', 'key': 'web_admin', 'label': '網頁管理員'},
    {'id': '513295891482804250', 'key': 'admin', 'label': '管理員'},
    {'id': '749803225275695156', 'key': 'regular_member', 'label': '正規成員'},
    {'id': '578156037589172244', 'key': 'member', 'label': '一般成員'},
)


def highest_role(role_ids):
    """Resolve the highest matching role; missing or malformed snapshots grant none.

    This is a mapping helper, not live authorization. Sensitive operations must
    verify current Discord membership before relying on a login-time snapshot.
    依優先順序取得最高網站身份組，無效資料或未匹配時不授予權限。

    Args:
        role_ids: Discord 身份組 ID 清單。

    Returns:
        dict | None: 最高匹配身份組的 id、key、label，無匹配時為 None。

    Example:
        >>> result = highest_role(role_ids=["578156037589172244"])
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    if not isinstance(role_ids, list) or not all(isinstance(role, str) for role in role_ids):
        return None
    return next((dict(role) for role in ACCESS_ROLES if role['id'] in role_ids), None)
