"""Account identity, authorization and guest-booking regressions."""

import re
import sqlite3

import pymysql
import pytest

import app as application


def csrf_token(client):
    return re.search(r'name="csrf_token" value="([^"]+)"', client.get("/book").text).group(1)


def submit(client, path, data=None):
    return client.post(path, data={**(data or {}), "csrf_token": csrf_token(client)})


def register(client, username="amara"):
    response = submit(client, "/signup", {"username": username, "password": "a-long-passphrase"})
    assert response.status_code == 303
    with client.session_transaction() as session:
        return session["user_id"]


def test_signup_signs_in_and_logout_clears_identity_and_receipt(client, database, booking_data):
    user_id = register(client)
    assert submit(client, "/book", booking_data).status_code == 303
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT user_id FROM tbl_appointment").fetchone()[0] == user_id
    assert submit(client, "/logout").status_code == 303
    with client.session_transaction() as session:
        assert "user_id" not in session
        assert "receipt" not in session
    assert client.get("/logout").status_code == 405
    assert client.get("/appointments").location.endswith("/login?next=appointments")
    assert client.get("/booking/received").status_code == 302


def test_login_verifies_password_and_returns_to_requested_page(client):
    expected = register(client)
    submit(client, "/logout")
    response = submit(client, "/login", {"username": "AMARA", "password": "a-long-passphrase", "next": "appointments"})
    assert response.status_code == 303
    assert response.location.endswith("/appointments")
    assert "HttpOnly" in response.headers["Set-Cookie"]
    assert "SameSite=Lax" in response.headers["Set-Cookie"]
    with client.session_transaction() as session:
        assert session["user_id"] == expected
        assert session.permanent
    assert client.get("/appointments").status_code == 200
    assert "Let’s plan their first visit." in client.get("/appointments").text
    assert client.get("/login").status_code == 302
    assert client.get("/signup").status_code == 302


@pytest.mark.parametrize("username,password", [
    ("amara", "wrong-passphrase"),
    ("unknown", "a-long-passphrase"),
    ("amara' OR 1=1 --", "a-long-passphrase"),
])
def test_bad_credentials_do_not_authenticate_or_reveal_account_existence(client, username, password):
    register(client)
    submit(client, "/logout")
    response = submit(client, "/login", {"username": username, "password": password})
    assert response.status_code == 401
    assert "That username or password doesn’t match" in response.text
    assert 'value="a-long-passphrase"' not in response.text
    with client.session_transaction() as session:
        assert "user_id" not in session


@pytest.mark.parametrize("data", [
    {}, {"username": "x" * 51, "password": "valid-password"},
    {"username": "amara", "password": "x" * 129},
])
def test_login_rejects_missing_and_overlong_input(client, data):
    assert submit(client, "/login", data).status_code == 422


def test_each_user_sees_only_their_own_appointments(app, client, database, booking_data):
    alice_id = register(client, "alice")
    bob = app.test_client()
    bob_id = register(bob, "bob")
    assert submit(client, "/book", {**booking_data, "pet_name": "Alice’s companion", "user_id": bob_id}).status_code == 303
    assert submit(bob, "/book", {**booking_data, "pet_name": "Bob’s companion"}).status_code == 303
    alice_page = client.get(f"/appointments?user_id={bob_id}").text
    bob_page = bob.get(f"/appointments?user_id={alice_id}").text
    assert "Alice’s companion" in alice_page and "Bob’s companion" not in alice_page
    assert "Bob’s companion" in bob_page and "Alice’s companion" not in bob_page
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT user_id FROM tbl_appointment WHERE pet_name=?", ("Alice’s companion",)).fetchone()[0] == alice_id


def test_guest_cannot_assign_an_owner_and_signup_does_not_claim_guest_history(client, database, booking_data):
    assert submit(client, "/book", {**booking_data, "pet_name": "Guest companion", "user_id": "123"}).status_code == 303
    assert client.get("/booking/received").status_code == 200
    register(client)
    assert "Guest companion" not in client.get("/appointments").text
    assert client.get("/booking/received").status_code == 302
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT user_id FROM tbl_appointment").fetchone()[0] is None


@pytest.mark.parametrize("path", ["/login", "/signup"])
@pytest.mark.parametrize("destination", ["https://example.com", "//example.com", "/appointments", "logout"])
def test_authentication_never_redirects_to_an_untrusted_destination(client, path, destination):
    if path == "/login":
        register(client)
        submit(client, "/logout")
    response = submit(client, path, {"username": "amara", "password": "a-long-passphrase", "next": destination})
    assert response.status_code == 303
    assert response.location == "/book"


def test_authentication_replaces_old_csrf_token(client):
    old_token = csrf_token(client)
    assert client.post("/signup", data={"username": "amara", "password": "a-long-passphrase", "csrf_token": old_token}).status_code == 303
    assert client.post("/logout", data={"csrf_token": old_token}).status_code == 400
    assert submit(client, "/logout").status_code == 303


def test_deleted_account_is_signed_out(client, database, booking_data):
    user_id = register(client)
    submit(client, "/book", booking_data)
    with sqlite3.connect(database) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("DELETE FROM tbl_user WHERE id=?", (user_id,))
        assert db.execute("SELECT user_id FROM tbl_appointment").fetchone()[0] is None
    assert client.get("/appointments").status_code == 302
    with client.session_transaction() as session:
        assert "user_id" not in session and "receipt" not in session


def test_account_lookup_failure_cannot_silently_save_a_guest_booking(monkeypatch, client, database, booking_data):
    register(client)
    token = csrf_token(client)

    def unavailable():
        raise pymysql.OperationalError(2003, "private connection details")

    monkeypatch.setattr(application, "get_db", unavailable)
    response = client.post("/book", data={**booking_data, "csrf_token": token})
    assert response.status_code == 503
    assert "private connection details" not in response.text
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM tbl_appointment").fetchone()[0] == 0
    # Logout remains possible even while MySQL is unavailable.
    assert client.post("/logout", data={"csrf_token": token}).status_code == 303


def test_login_database_failure_returns_retry_message(monkeypatch, client):
    token = csrf_token(client)

    def unavailable():
        raise pymysql.OperationalError(2003, "private connection details")

    monkeypatch.setattr(application, "get_db", unavailable)
    response = client.post("/login", data={"username": "amara", "password": "a-long-passphrase", "csrf_token": token})
    assert response.status_code == 503
    assert "couldn’t sign you in" in response.text
    assert "private connection details" not in response.text


def test_appointment_read_failure_is_not_an_empty_history(monkeypatch, client):
    from conftest import Cursor
    original = Cursor.execute
    register(client)

    def unavailable(self, query, params=()):
        if "FROM tbl_appointment" in query:
            raise pymysql.OperationalError(2013, "Connection lost")
        return original(self, query, params)

    monkeypatch.setattr(Cursor, "execute", unavailable)
    response = client.get("/appointments")
    assert response.status_code == 503
    assert "couldn’t load your appointments" in response.text
    assert "Let’s plan their first visit." not in response.text


def test_authentication_attempt_limit_expires(monkeypatch, app, client):
    app.config.update(AUTH_RATE_LIMIT=2, AUTH_RATE_WINDOW=60)
    clock = [100.0]
    monkeypatch.setattr(application, "monotonic", lambda: clock[0])
    data = {"username": "unknown", "password": "wrong-passphrase"}
    assert submit(client, "/login", data).status_code == 401
    assert submit(client, "/login", data).status_code == 401
    limited = submit(client, "/login", data)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0
    clock[0] += 61
    assert submit(client, "/login", data).status_code == 401


def test_account_notes_and_names_remain_escaped(client, booking_data):
    register(client)
    submit(client, "/book", {**booking_data, "pet_name": "<script>alert(1)</script>", "notes": "<img src=x onerror=alert(1)>"})
    response = client.get("/appointments")
    assert response.status_code == 200
    assert "&lt;script&gt;" in response.text and "&lt;img" in response.text
    assert "<script>alert(1)</script>" not in response.text
