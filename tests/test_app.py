import re
import sqlite3

import pymysql
import pytest
from werkzeug.security import check_password_hash

import app as application


def token(client, path):
    response = client.get(path)
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text).group(1)


def post(client, path, data, **kwargs):
    return client.post(path, data={**data, "csrf_token": token(client, "/book" if path == "/logout" else path)}, **kwargs)


@pytest.mark.parametrize("path", ["/", "/signup", "/book", "/book?service=grooming"])
def test_pages_render(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert "paw" in response.text
    assert "Content-Security-Policy" in response.headers


def test_signup_stores_salted_hash_and_rejects_duplicate(client, database):
    password = "a-long-test-passphrase"
    response = post(client, "/signup", {"username": "amara", "password": password})
    assert response.status_code == 303
    with sqlite3.connect(database) as db:
        stored = db.execute("SELECT password FROM tbl_user WHERE username='amara'").fetchone()[0]
    assert stored != password
    assert stored.startswith("scrypt:")
    assert check_password_hash(stored, password)
    assert not check_password_hash(stored, "wrong-password")
    with client.session_transaction() as session:
        assert session["user_id"] > 0
    assert post(client, "/logout", {}).status_code == 303
    response = post(client, "/signup", {"username": "AMARA", "password": password})
    assert response.status_code == 422
    assert "already taken" in response.text
    assert password not in response.text


@pytest.mark.parametrize("data", [
    {"username": "x", "password": "long-password"},
    {"username": "amara", "password": "short"},
    {"username": "x' OR 1=1 --", "password": "long-password"},
    {"username": "x" * 51, "password": "long-password"},
    {"username": "amara", "password": "x" * 129},
])
def test_invalid_signup_does_not_write(client, database, data):
    assert post(client, "/signup", data).status_code == 422
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM tbl_user").fetchone()[0] == 0


def test_booking_persists_and_returns_pending_receipt(client, booking_data, database):
    response = post(client, "/book", booking_data, follow_redirects=True)
    assert response.status_code == 200
    assert response.request.path == "/booking/received"
    assert "Awaiting confirmation" in response.text
    assert "10:30 AM" in response.text
    with sqlite3.connect(database) as db:
        row = db.execute("SELECT pet_name, service, preferred_date, preferred_time, status, reference FROM tbl_appointment").fetchone()
        assert row[:5] == ("Milo", "consultation", "2026-11-11", "10:30", "pending")
        assert row[5] in response.text
        # Reloading the receipt must not repeat the write.
        client.get("/booking/received")
        assert db.execute("SELECT COUNT(*) FROM tbl_appointment").fetchone()[0] == 1
    with client.session_transaction() as session:
        assert "email" not in session["receipt"]
        assert "phone" not in session["receipt"]


@pytest.mark.parametrize("field,value,expected", [
    ("owner_name", "", "Your name is required"),
    ("pet_name", "", "Your pet’s name is required"),
    ("pet_name", "x" * 81, "up to 80 characters"),
    ("email", "not-an-email", "valid email"),
    ("phone", "abcd1234", "valid phone"),
    ("species", "Unicorn", "choose your pet’s species"),
    ("service", "surgery", "choose a service"),
    ("date", "2026-11-09", "future date"),
    ("date", "2026-11-15", "closed on Sundays"),
    ("date", "2026-02-30", "valid date"),
    ("time", "22:00", "9:00 am and 4:30 pm"),
    ("notes", "x" * 1001, "1,000 characters"),
])
def test_invalid_booking_keeps_details_and_does_not_write(client, database, booking_data, field, value, expected):
    booking_data[field] = value
    response = post(client, "/book", booking_data)
    assert response.status_code == 422
    assert expected in response.text
    assert 'value="amara@example.com"' in response.text or field == "email"
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM tbl_appointment").fetchone()[0] == 0


def test_same_day_passed_time_is_rejected(client, booking_data):
    response = post(client, "/book", {**booking_data, "date": "2026-11-10", "time": "09:30"})
    assert response.status_code == 422
    assert "That time has passed" in response.text


def test_future_same_day_is_accepted(client, booking_data):
    assert post(client, "/book", {**booking_data, "date": "2026-11-10", "time": "10:30"}).status_code == 303


def test_sql_and_html_payloads_are_data(client, database, booking_data):
    payload = "Milo'); DROP TABLE tbl_user; --"
    response = post(client, "/book", {**booking_data, "pet_name": payload, "notes": "<script>alert(1)</script>"})
    assert response.status_code == 303
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT pet_name FROM tbl_appointment").fetchone()[0] == payload
        assert db.execute("SELECT COUNT(*) FROM tbl_user").fetchone()[0] == 0
    response = post(client, "/book", {**booking_data, "pet_name": "<script>alert(1)</script>", "email": "invalid"})
    assert response.status_code == 422
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


@pytest.mark.parametrize("path", ["/signup", "/login", "/logout", "/book"])
def test_csrf_required(client, path):
    assert client.post(path, data={}).status_code == 400
    assert client.post(path, data={"csrf_token": "forged"}).status_code == 400


def test_csrf_from_another_session_is_rejected(app, client, booking_data):
    other = app.test_client()
    assert other.post("/book", data={**booking_data, "csrf_token": token(client, "/book")}).status_code == 400


def test_expired_csrf_token_is_rejected(monkeypatch, client, booking_data):
    from itsdangerous import TimestampSigner
    original = TimestampSigner.get_timestamp
    with monkeypatch.context() as patch:
        patch.setattr(TimestampSigner, "get_timestamp", lambda self: original(self) - 7200)
        expired = token(client, "/book")
    assert client.post("/book", data={**booking_data, "csrf_token": expired}).status_code == 400


@pytest.mark.parametrize("path,data", [
    ("/signup", {"username": "amara", "password": "a-long-password"}),
    ("/book", None),
])
def test_database_failure_does_not_claim_success(monkeypatch, client, booking_data, path, data):
    def unavailable():
        raise pymysql.OperationalError(2003, "private database detail")
    monkeypatch.setattr(application, "get_db", unavailable)
    response = post(client, path, data or booking_data)
    assert response.status_code == 503
    assert "couldn’t save" in response.text
    assert "private database detail" not in response.text
    with client.session_transaction() as session:
        assert "receipt" not in session


def test_preselection_and_navigation(client):
    response = client.get("/book?service=grooming")
    assert 'value="grooming" selected' in response.text
    assert 'value="surgery"' not in client.get("/book?service=surgery").text
    assert client.get("/booking/received").status_code == 302
    assert client.get("/not-here").status_code == 404


def test_connection_loss_and_failed_rollback_return_useful_error(monkeypatch, client, booking_data):
    from conftest import Connection

    def disconnected(self):
        raise pymysql.OperationalError(2013, "Connection lost")

    monkeypatch.setattr(Connection, "commit", disconnected)
    monkeypatch.setattr(Connection, "rollback", disconnected)
    response = post(client, "/book", booking_data)
    assert response.status_code == 503
    assert "Your details are still here" in response.text
    assert "Connection lost" not in response.text


def test_large_submissions_are_rejected(client):
    assert client.post("/book", data={"notes": "x" * 40000}).status_code == 413
