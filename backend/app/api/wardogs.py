"""Public local Wardogs data and immutable release icons."""
from flask import Blueprint, current_app, jsonify, send_from_directory
from app.services.wardogs import CACHE_VERSION, WardogsError

wardogs_bp = Blueprint('wardogs', __name__)


@wardogs_bp.get('/items')
def items():
    try:
        response = jsonify(current_app.extensions['wardogs'].read())
        response.headers['Cache-Control'] = 'no-store'
        return response
    except WardogsError as error:
        return jsonify(error=str(error)), 503


@wardogs_bp.get('/icons/<release>/<path:filename>')
def icon(release, filename):
    if not release.isdigit():
        return '', 404
    return send_from_directory(current_app.extensions['wardogs'].path / release / 'icons', filename, max_age=31536000)


@wardogs_bp.get('/datasets')
def datasets():
    """List all locally downloaded source datasets, including nested maps and schemas."""
    service = current_app.extensions['wardogs']
    try:
        data = service.read()
    except WardogsError as error:
        return jsonify(error=str(error)), 503
    root = service.path / data['release'] / 'data'
    files = sorted(path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file())
    response = jsonify(release=data['release'], gameBuild=data['gameBuild'], files=files,
                       complete=data.get('cacheVersion') == CACHE_VERSION)
    response.headers['Cache-Control'] = 'no-store'
    return response


@wardogs_bp.get('/data/<release>/<path:filename>')
def source_data(release, filename):
    """Serve original JSON, CSV and schema files from the selected local snapshot."""
    if not release.isdigit():
        return '', 404
    return send_from_directory(current_app.extensions['wardogs'].path / release / 'data', filename, max_age=31536000)


@wardogs_bp.get('/assets/<release>/<path:filename>')
def source_asset(release, filename):
    """Serve locally cached icons, map tiles, heightmaps and manifests."""
    if not release.isdigit():
        return '', 404
    return send_from_directory(current_app.extensions['wardogs'].path / release / 'assets', filename, max_age=31536000)


@wardogs_bp.get('/items/<path:item_id>')
def item_detail(item_id):
    """Return verified cross-source detail records for one item."""
    from app.services.wardogs_details import item_details
    service = current_app.extensions['wardogs']
    try:
        data = service.read()
        details = item_details(service.path / data['release'] / 'data', item_id)
        if details is None:
            return jsonify(error='找不到此物品。'), 404
        response = jsonify(**details, release=data['release'])
        response.headers['Cache-Control'] = 'no-store'
        return response
    except WardogsError as error:
        return jsonify(error=str(error)), 503
