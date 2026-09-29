"""Expose the demo user collection separately from authenticated member profiles."""
from flask import Blueprint, jsonify
from app.services.users import get_users

users_bp = Blueprint("users", __name__)


@users_bp.get("", strict_slashes=False)
def list_users():
    """Return the static demo users as a JSON collection; no database is queried."""
    return jsonify(users=get_users())
