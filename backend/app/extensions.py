"""Attach application-scoped infrastructure without opening a database eagerly."""
from flask import Flask

from app.sql import SQLManager


def init_extensions(app: Flask) -> None:
    """Attach a file-backed SQL manager using the configured database path."""
    app.extensions["sql"] = SQLManager(app.config["SQL_DATABASE_PATH"])
