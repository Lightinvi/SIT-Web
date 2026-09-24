def get_users():
    """Return demo records until a persistent user store is connected."""
    return [
        {"id": 1, "name": "Alex Chen", "email": "alex@example.com", "role": "管理員", "status": "active"},
        {"id": 2, "name": "Jamie Lin", "email": "jamie@example.com", "role": "編輯者", "status": "active"},
        {"id": 3, "name": "Sam Wang", "email": "sam@example.com", "role": "成員", "status": "invited"},
    ]
