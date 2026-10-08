"""Provide demo users until the public user listing has a persistent data source."""
def get_users():
    """Return demo records until a persistent user store is connected.
    取得公開用戶列表的示範資料。

    Args:
        None: 無需傳入參數。

    Returns:
        list[dict]: 示範用戶資料。

    Example:
        >>> result = get_users()
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    return [
        {"id": 1, "name": "Alex Chen", "email": "alex@example.com", "role": "管理員", "status": "active"},
        {"id": 2, "name": "Jamie Lin", "email": "jamie@example.com", "role": "編輯者", "status": "active"},
        {"id": 3, "name": "Sam Wang", "email": "sam@example.com", "role": "成員", "status": "invited"},
    ]
