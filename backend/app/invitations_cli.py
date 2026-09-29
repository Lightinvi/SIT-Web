"""Local administration commands for invitation settings without exposing a write API."""
import sqlite3

import click
from flask import current_app
from flask.cli import with_appcontext

from app.models.invitation import ROLES, ensure_schema, valid_code


@click.group('invitations')
def invitations_cli():
    """Manage Discord invitation settings stored in the application database."""


@invitations_cli.command('set')
@click.option('--role', required=True, type=click.Choice(ROLES))
@click.option('--code', required=True)
@click.option('--description', default=None)
@click.option('--expired/--active', default=False)
@with_appcontext
def set_invitation(role, code, description, expired):
    """Update an invite without rebuilding images or overwriting click history."""
    if not valid_code(code):
        raise click.BadParameter('Provide only the final Discord invitation code.', param_hint='--code')
    db = current_app.extensions['sql']
    ensure_schema(db)
    try:
        with db.transaction(immediate=True) as tx:
            previous = tx.select('invitation_url', {'role': role})
            text = description if description is not None else previous[0]['description'] if previous else ''
            if not text.strip():
                raise click.BadParameter('A nonempty description is required.', param_hint='--description')
            tx.execute('''INSERT INTO invitation_url (code, role, description, isExpired)
                VALUES (?, ?, ?, ?) ON CONFLICT(role) DO UPDATE SET
                code=excluded.code, description=excluded.description, isExpired=excluded.isExpired''',
                       (code, role, text, int(expired)))
    except sqlite3.IntegrityError as error:
        raise click.ClickException('This invitation code is already assigned to another role.') from error
    click.echo(f'Updated {role}: {code} (expired={expired})')
