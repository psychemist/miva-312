"""Database setup and migration tests."""

from pathlib import Path

from flask import Flask

import db_setup


ROOT = Path(__file__).resolve().parents[1]


class RecordingDB:
    def __init__(self, linked=True):
        self.linked = linked
        self.queries = []
        self.commits = 0
        self.closed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, query, params=()):
        self.queries.append((query, params))
        if "ALTER TABLE tbl_appointment" in query:
            self.linked = True

    def fetchone(self):
        return {"COLUMN_NAME": "user_id"} if self.linked else None

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def test_old_table_upgrade_runs_once_without_dropping_tables():
    db = RecordingDB(linked=False)
    db_setup.initialize_tables(db, ROOT)
    db_setup.initialize_tables(db, ROOT)
    sql = [query for query, _ in db.queries]
    assert sum("ALTER TABLE tbl_appointment" in query for query in sql) == 1
    assert not any("DROP TABLE" in query.upper() for query in sql)
    assert "ON DELETE SET NULL" in next(query for query in sql if "ALTER TABLE" in query)
    assert db.commits == 2


def test_fresh_schema_does_not_run_legacy_alter():
    db = RecordingDB(linked=True)
    db_setup.initialize_tables(db, ROOT)
    assert not any("ALTER TABLE" in query for query, _ in db.queries)


def test_native_setup_uses_env_password_without_printing_or_resetting_existing_accounts(monkeypatch):
    admin, application = RecordingDB(), RecordingDB()
    monkeypatch.setenv("MYSQL_DATABASE", "pawkin_test")
    monkeypatch.setenv("MYSQL_USER", "pawkin_test")
    monkeypatch.setenv("MYSQL_PASSWORD", "only-a-test-password")
    monkeypatch.setattr(db_setup.pymysql, "connect", lambda **kwargs: admin)
    app = Flask(__name__, root_path=str(ROOT))
    db_setup.register_db_commands(app, lambda: application)
    result = app.test_cli_runner().invoke(args=["setup-db"], input="\n")
    assert result.exit_code == 0, result.output
    assert "only-a-test-password" not in result.output
    assert admin.closed
    assert application.commits == 1
    sql = [query for query, _ in admin.queries]
    assert sum("CREATE USER IF NOT EXISTS" in query for query in sql) == 2
    assert not any("ALTER USER" in query for query in sql)


def test_native_setup_rejects_unsafe_database_identifier_before_connecting(monkeypatch):
    monkeypatch.setenv("MYSQL_DATABASE", "pawkin`; DROP DATABASE other; --")
    app = Flask(__name__, root_path=str(ROOT))
    db_setup.register_db_commands(app, lambda: None)
    result = app.test_cli_runner().invoke(args=["setup-db"])
    assert result.exit_code != 0
    assert "simple database name" in result.output
