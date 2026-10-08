"""Create isolated Flask applications with SQL, Discord, and authentication routes."""
import os
from datetime import timedelta
from pathlib import Path

from flask import Flask

from app.services.discord import DiscordService
from app.services.roles import ACCESS_ROLES

from app.config import Config
from app.extensions import init_extensions
from app.logging_setup import init_logging


def create_app(config=None):
    """Build an app from environment settings and optional mapping overrides.

    Initialize a separate SQL manager and Discord cache service for this app.
    Configuration overrides are applied before extensions and routes are registered.
    依環境設定與覆寫配置建立 Flask 應用程式，註冊服務、擴充套件與路由。

    Args:
        config: 覆寫預設應用設定的對照表；None 使用環境與預設設定。 預設為 None。

    Returns:
        Flask: 已完成配置與路由註冊的應用程式。

    Example:
        >>> result = create_app()
        db、instance 與其餘範例變數須先依 Args 建立；範例 ID 涉及成員時須先有對應資料。
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        DISCORD_CLIENT_ID=os.environ.get("DISCORD_CLIENT_ID") or os.environ.get("DISCORD_BOT_CLIENT_ID", ""),
        DISCORD_CLIENT_SECRET=os.environ.get("DISCORD_CLIENT_SECRET", ""),
        DISCORD_REDIRECT_URI=os.environ.get("DISCORD_REDIRECT_URI", ""),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),
        SQL_DATABASE_PATH=str(Path(os.environ.get("STORAGE_PATH", Path(__file__).resolve().parents[2] / "storage")) / "database" / "sit.sqlite3"),
        DISCORD_BOT_TOKEN=os.environ.get("DISCORD_BOT_TOKEN", ""),
        DISCORD_GUILD_ID="510386488639488001",
        DISCORD_ADMIN_ROLE_IDS=('513295891482804250',),
        DISCORD_LOGIN_ROLE_IDS=tuple(role['id'] for role in ACCESS_ROLES),
        DISCORD_CACHE_PATH=str(Path(os.environ.get("STORAGE_PATH", Path(__file__).resolve().parents[2] / "storage")) / "cache"),
        LOG_DIRECTORY=os.environ.get('LOG_DIRECTORY', str(Path(os.environ.get('STORAGE_PATH', Path(__file__).resolve().parents[2] / 'storage')) / 'logs')),
    )
    if config is not None:
        app.config.from_mapping(config)

    init_logging(app)
    init_extensions(app)
    app.extensions["discord"] = DiscordService(
        app.config["DISCORD_BOT_TOKEN"], app.config["DISCORD_GUILD_ID"],
        app.config["DISCORD_CACHE_PATH"],
    )

    from app.api.discord import discord_bp
    from app.api.auth import auth_bp
    from app.api.admin import admin_bp
    from app.api.users import users_bp
    from app.api.invitations import invitations_bp
    from app.api.star_shard import shards_bp
    from app.api.daily_spinner import spinner_bp
    from app.api.blackjack import blackjack_bp
    from app.api.prediction import prediction_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(shards_bp, url_prefix="/api/star-shards")
    app.register_blueprint(spinner_bp, url_prefix="/api/daily-spinner")
    app.register_blueprint(blackjack_bp, url_prefix="/api/blackjack")
    app.register_blueprint(prediction_bp, url_prefix="/api/predictions")
    app.register_blueprint(users_bp, url_prefix="/api/users")
    app.register_blueprint(invitations_bp, url_prefix="/api/invitations")

    app.register_blueprint(discord_bp, url_prefix="/api/discord")

    @app.get('/api/health')
    def health():
        """Report HTTP liveness without accessing Discord or application data.
        回報 HTTP 服務存活狀態，不查詢資料庫或 Discord。

        Args:
            None: 無需傳入參數；實例方法使用目前物件狀態。

        Returns:
            Response | tuple[Response, int]: Flask 回應；拒絕請求時可能附帶 HTTP 狀態碼。

        Example:
            >>> client = app.test_client()
            >>> response = client.get('/api/health')
            受保護端點須先為測試用戶端建立有效登入；POST 的 payload 與 headers 須依端點準備。
        """
        return {'status': 'ok'}

    return app
