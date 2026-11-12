"""MySQL database setup and schema migrations."""

import os
import re
import ssl
from pathlib import Path

import click
import pymysql


def mysql_tls_options():
    """Use certificate and hostname verification for hosted MySQL connections."""
    enabled = os.getenv("MYSQL_SSL", "false").strip().lower()
    if enabled not in {"true", "false"}:
        raise ValueError("MYSQL_SSL must be true or false.")
    if enabled == "false":
        return {}
    ca = os.getenv("MYSQL_SSL_CA") or None
    return {"ssl": ssl.create_default_context(cadata=ca)}


def initialize_tables(db, root):
    schema = Path(root, "schema.sql").read_text()
    with db.cursor() as cursor:
        for statement in schema.split(";"):
            if statement.strip():
                cursor.execute(statement)
        cursor.execute(
            """SELECT COLUMN_NAME FROM information_schema.COLUMNS
               WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='tbl_appointment'
               AND COLUMN_NAME='user_id'"""
        )
        if not cursor.fetchone():
            cursor.execute(Path(root, "migrations", "001_link_appointments.sql").read_text())
    db.commit()


def register_db_commands(app, get_db):
    @app.cli.command("init-db")
    def init_db():
        """Create tables and add account ownership to an older booking table."""
        try:
            initialize_tables(get_db(), app.root_path)
        except pymysql.MySQLError as exc:
            raise click.ClickException(
                "Cannot initialize MySQL. Check .env and make sure the database exists."
            ) from exc
        click.echo("MySQL tables ready: tbl_user and tbl_appointment.")

    @app.cli.command("setup-db")
    @click.option("--admin-user", default="root", show_default=True, help="Your local MySQL administrator.")
    def setup_db(admin_user):
        """Create the local database, application account, and tables."""
        database = os.getenv("MYSQL_DATABASE", "pawkin")
        username = os.getenv("MYSQL_USER", "pawkin")
        password = os.getenv("MYSQL_PASSWORD", "")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", database):
            raise click.ClickException("MYSQL_DATABASE must be a simple database name (letters, numbers, underscores).")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,32}", username) or username == admin_user:
            raise click.ClickException("Set MYSQL_USER to a separate application account, such as pawkin.")
        if not password or password == "choose-a-local-database-password":
            raise click.ClickException("Set MYSQL_PASSWORD in .env before running setup-db.")
        admin_password = click.prompt(
            "MySQL administrator password (Enter if blank)", hide_input=True,
            default="", show_default=False,
        )
        admin = None
        try:
            admin = pymysql.connect(
                host=os.getenv("MYSQL_HOST", "127.0.0.1"),
                port=int(os.getenv("MYSQL_PORT", "3306")),
                user=admin_user, password=admin_password,
                charset="utf8mb4", autocommit=True, connect_timeout=5,
                **mysql_tls_options(),
            )
            with admin.cursor() as cursor:
                # Only the validated identifier is interpolated; account names
                # and passwords are always passed as query parameters.
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{database}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                for host in ("127.0.0.1", "localhost"):
                    cursor.execute("CREATE USER IF NOT EXISTS %s@%s IDENTIFIED BY %s", (username, host, password))
                    cursor.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES ON `{database}`.* TO %s@%s", (username, host))
            initialize_tables(get_db(), app.root_path)
        except pymysql.MySQLError as exc:
            raise click.ClickException(
                "MySQL setup failed. Start your local MySQL server and check the administrator credentials. "
                "If the application account already exists, MYSQL_PASSWORD must match its existing password."
            ) from exc
        finally:
            if admin is not None:
                admin.close()
        click.echo("MySQL database, application account, and tables are ready.")
