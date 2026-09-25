import os
from pathlib import Path

from flask import Flask

from app.services.discord import DiscordService

from app.config import Config
from app.extensions import init_extensions


def create_app(config=None):
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
        PERMANENT_SESSION_LIFETIME=28800,
        SQL_DATABASE_PATH=str(Path(os.environ.get("STORAGE_PATH", Path(__file__).resolve().parents[2] / "storage")) / "database" / "sit.sqlite3"),
        DISCORD_BOT_TOKEN=os.environ.get("DISCORD_BOT_TOKEN", ""),
        DISCORD_GUILD_ID="510386488639488001",
        DISCORD_CACHE_PATH=str(Path(os.environ.get("STORAGE_PATH", Path(__file__).resolve().parents[2] / "storage")) / "cache"),
    )
    if config is not None:
        app.config.from_mapping(config)

    init_extensions(app)
    app.extensions["discord"] = DiscordService(
        app.config["DISCORD_BOT_TOKEN"], app.config["DISCORD_GUILD_ID"],
        app.config["DISCORD_CACHE_PATH"],
    )

    from app.api.discord import discord_bp
    from app.api.auth import auth_bp
    from app.api.users import users_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(users_bp, url_prefix="/api/users")

    app.register_blueprint(discord_bp, url_prefix="/api/discord")

    return app
