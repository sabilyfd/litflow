"""
`flask user` CLI — the only way to create local username/password accounts.

There is no signup route by design. Run inside the web container, e.g.:

    docker compose exec web flask --app web.app user create alice --admin
    docker compose exec web flask --app web.app user list
    docker compose exec web flask --app web.app user passwd alice
    docker compose exec web flask --app web.app user delete alice
"""

import sqlite3
from datetime import datetime, timezone

import click
from flask import Blueprint

from web import db
from web.passwords import hash_password

user_cli = Blueprint("user_cli", __name__, cli_group="user")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@user_cli.cli.command("create")
@click.argument("username")
@click.option("--name", default="", help="Display name (defaults to the username).")
@click.option("--email", default="", help="Email address.")
@click.option("--admin", is_flag=True, help="Grant admin access.")
@click.password_option(help="Account password (prompted if omitted).")
def create_cmd(username: str, name: str, email: str, admin: bool, password: str) -> None:
    """Create a local user account."""
    db.init_db()
    try:
        db.create_user(
            username=username,
            password_hash=hash_password(password),
            name=name or username,
            email=email,
            is_admin=admin,
            created_at=_now(),
        )
    except sqlite3.IntegrityError:
        raise click.ClickException(f"User {username!r} already exists.")
    click.echo(f"Created user {username!r}{' (admin)' if admin else ''}.")


@user_cli.cli.command("list")
def list_cmd() -> None:
    """List local user accounts."""
    db.init_db()
    users = db.list_users()
    if not users:
        click.echo("No local users.")
        return
    for u in users:
        flag = "admin" if u["is_admin"] else "user"
        click.echo(f"{u['username']:<20} {flag:<6} {u['email']}")


@user_cli.cli.command("passwd")
@click.argument("username")
@click.password_option(help="New password (prompted if omitted).")
def passwd_cmd(username: str, password: str) -> None:
    """Reset a local user's password."""
    db.init_db()
    if not db.set_user_password(username, hash_password(password)):
        raise click.ClickException(f"User {username!r} not found.")
    click.echo(f"Password updated for {username!r}.")


@user_cli.cli.command("delete")
@click.argument("username")
@click.confirmation_option(prompt="Delete this user?")
def delete_cmd(username: str) -> None:
    """Delete a local user account."""
    db.init_db()
    if not db.delete_user(username):
        raise click.ClickException(f"User {username!r} not found.")
    click.echo(f"Deleted user {username!r}.")
