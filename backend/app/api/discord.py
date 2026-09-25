from flask import Blueprint, current_app, jsonify

from app.services.discord import DiscordError


discord_bp = Blueprint('discord', __name__)


def respond(resource):
    try:
        response = jsonify(current_app.extensions['discord'].get(resource))
    except DiscordError as error:
        response = jsonify(error=str(error))
        response.status_code = error.status
        response.headers['Retry-After'] = str(error.retry_after)
    response.headers['Cache-Control'] = 'no-store'
    return response


@discord_bp.get('/members', strict_slashes=False)
def list_members():
    return respond('members')


@discord_bp.get('/roles', strict_slashes=False)
def list_roles():
    return respond('roles')
