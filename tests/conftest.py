"""Offline route tests use SQLite only as a transactional MySQL test double.

The application itself supports MySQL exclusively. This adapter checks form
behavior and real writes/uniqueness; it does not establish MySQL compatibility.
"""

import sqlite3
from datetime import datetime

import pymysql
import pytest

import app as application


class Cursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.cursor = self.connection.cursor()
        return self

    def __exit__(self, *args):
        self.cursor.close()

    def execute(self, query, params=()):
        try:
            self.cursor.execute(query.replace("%s", "?"), params)
        except sqlite3.IntegrityError as error:
            raise pymysql.IntegrityError(1062, "Duplicate entry") from error


class Connection:
    def __init__(self, path):
        self.connection = sqlite3.connect(path)

    def cursor(self):
        return Cursor(self.connection)

    def commit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def close(self):
        self.connection.close()


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "test.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE tbl_user (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE COLLATE NOCASE,
                password TEXT
            );
            CREATE TABLE tbl_appointment (
                id INTEGER PRIMARY KEY, reference TEXT UNIQUE, owner_name TEXT,
                email TEXT, phone TEXT, pet_name TEXT, species TEXT, service TEXT,
                preferred_date TEXT, preferred_time TEXT, notes TEXT,
                status TEXT DEFAULT 'pending'
            );
        """)
    return path


@pytest.fixture
def app(monkeypatch, database):
    def connection():
        if "db" not in application.g:
            application.g.db = Connection(database)
        return application.g.db

    monkeypatch.setattr(application, "get_db", connection)
    monkeypatch.setattr(application, "clinic_now", lambda: datetime(2026, 11, 10, 10, 0, tzinfo=application.CLINIC_TIMEZONE))
    return application.create_app({"TESTING": True, "SECRET_KEY": "only-for-tests"})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def booking_data():
    return {
        "owner_name": "Amara Okafor", "email": "amara@example.com",
        "phone": "+234 800 000 0000", "pet_name": "Milo", "species": "Dog",
        "service": "consultation", "date": "2026-11-11", "time": "10:30",
        "notes": "A little nervous on first visits.",
    }
