from flask import Flask

from app.sql import SQLManager


def init_extensions(app: Flask) -> None:
    app.extensions["sql"] = SQLManager(app.config["SQL_DATABASE_PATH"])
