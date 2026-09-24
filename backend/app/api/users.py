from flask import Blueprint, jsonify
from app.services.users import get_users

users_bp = Blueprint("users", __name__)


@users_bp.get("", strict_slashes=False)
def list_users():
    return jsonify(users=get_users())
