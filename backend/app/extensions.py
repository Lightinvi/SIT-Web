"""Attach application-scoped infrastructure without opening a database eagerly."""
from flask import Flask

from app.sql import SQLManager
from app.services.container import ApplicationServices


def init_extensions(app: Flask) -> None:
    """Attach a file-backed SQL manager using the configured database path.
    為應用程式註冊獨立的 SQL 管理器。

    Args:
        app (Flask): 待設定的 Flask 應用程式。

    Returns:
        None: 僅更新狀態或執行副作用，不回傳資料。

    Example:
        >>> result = init_extensions(app=app)
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    app.extensions["sql"] = SQLManager(app.config["SQL_DATABASE_PATH"])
    app.extensions["services"] = ApplicationServices(app.extensions["sql"], app.config)
