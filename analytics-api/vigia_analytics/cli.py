"""Command line tasks: ``flask --app vigia_analytics <command>``."""

import click
from flask import Flask

from . import repository as repo
from .extensions import get_engine
from .security import ROLES, hash_password


def register_cli(app: Flask) -> None:
    @app.cli.command("create-user")
    @click.argument("username")
    @click.option("--role", type=click.Choice(ROLES), default="viewer", show_default=True)
    @click.option(
        "--password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        envvar="VIGIA_USER_PASSWORD",
        help="Prompted if omitted. Scripts can pass it in VIGIA_USER_PASSWORD.",
    )
    def create_user(username: str, role: str, password: str) -> None:
        """Create an API user, or update the password and role of an existing one."""
        if len(password) < 8:
            raise click.BadParameter("use at least 8 characters", param_hint="--password")
        with get_engine().begin() as conn:
            repo.upsert_user(conn, username, hash_password(password), role)
        click.echo(f"User '{username}' saved with role '{role}'.")

    @app.cli.command("refresh-stats")
    def refresh_stats() -> None:
        """Rebuild the mv_app_daily_stats materialized view."""
        with get_engine().begin() as conn:
            repo.refresh_daily_stats(conn)
        click.echo("mv_app_daily_stats refreshed.")
