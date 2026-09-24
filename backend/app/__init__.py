from flask import Flask

from app.config import Config
from app.extensions import init_extensions


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config is not None:
        app.config.from_mapping(config)

    init_extensions(app)

    from app.api.auth import auth_bp
    from app.api.users import users_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(users_bp, url_prefix="/api/users")

    return app
