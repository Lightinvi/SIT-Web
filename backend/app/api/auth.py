from flask import Blueprint, jsonify

auth_bp = Blueprint("auth", __name__)


@auth_bp.get("/session")
def session_status():
    return jsonify(authenticated=False)
