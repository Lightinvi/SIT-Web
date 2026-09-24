from flask import Flask


def init_extensions(app: Flask) -> None:
    """Initialize future extensions with extension.init_app(app)."""
