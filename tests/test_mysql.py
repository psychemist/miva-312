"""Integration tests against the configured MySQL server."""

import os
import re
import uuid
from datetime import timedelta

import pytest
from werkzeug.security import check_password_hash

import app as application


@pytest.mark.skipif(os.getenv("MYSQL_INTEGRATION") != "1", reason="Set MYSQL_INTEGRATION=1 with a configured MySQL server")
def test_real_mysql_signup_and_booking():
    app = application.create_app({"TESTING": True})
    client = app.test_client()
    username = "integration_" + uuid.uuid4().hex[:20]
    reference = None
    guest_reference = None
    other_username = "integration_" + uuid.uuid4().hex[:20]

    def post(path, data):
        html = client.get("/book" if path == "/logout" else path).text
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        return client.post(path, data={**data, "csrf_token": token})

    try:
        response = post("/signup", {"username": username, "password": "integration-passphrase"})
        assert response.status_code == 303
        with app.app_context():
            with application.get_db().cursor() as cursor:
                cursor.execute("SELECT id, password FROM tbl_user WHERE username=%s", (username,))
                user = cursor.fetchone()
                assert check_password_hash(user["password"], "integration-passphrase")
                user_id = user["id"]
        future = application.clinic_now().date() + timedelta(days=1)
        if future.weekday() == 6:
            future += timedelta(days=1)
        response = post("/book", {
            "owner_name": "Integration Test", "email": "integration@example.com",
            "phone": "+2348000000000", "pet_name": "Test Pet", "species": "Dog",
            "service": "consultation", "date": future.isoformat(), "time": "10:30", "notes": "",
        })
        assert response.status_code == 303
        with client.session_transaction() as session:
            reference = session["receipt"]["reference"]
        with app.app_context():
            with application.get_db().cursor() as cursor:
                cursor.execute("SELECT status, preferred_date, user_id FROM tbl_appointment WHERE reference=%s", (reference,))
                row = cursor.fetchone()
                assert row["status"] == "pending"
                assert row["preferred_date"] == future
                assert row["user_id"] == user_id
        assert reference in client.get("/appointments").text
        assert post("/logout", {}).status_code == 303
        assert client.get("/appointments").status_code == 302
        assert post("/login", {"username": username, "password": "wrong-password"}).status_code == 401
        assert post("/login", {"username": username, "password": "integration-passphrase", "next": "appointments"}).status_code == 303
        assert reference in client.get("/appointments").text
        assert post("/logout", {}).status_code == 303
        assert post("/signup", {"username": other_username, "password": "integration-passphrase"}).status_code == 303
        assert reference not in client.get(f"/appointments?user_id={user_id}").text
        assert post("/logout", {}).status_code == 303
        guest = post("/book", {
            "owner_name": "Guest Integration", "email": "guest@example.com",
            "phone": "+2348000000000", "pet_name": "Guest Test Pet", "species": "Cat",
            "service": "wellness", "date": future.isoformat(), "time": "11:30", "notes": "",
            "user_id": str(user_id),
        })
        assert guest.status_code == 303
        with client.session_transaction() as session:
            guest_reference = session["receipt"]["reference"]
        with app.app_context():
            with application.get_db().cursor() as cursor:
                cursor.execute("SELECT user_id FROM tbl_appointment WHERE reference=%s", (guest_reference,))
                assert cursor.fetchone()["user_id"] is None
    finally:
        with app.app_context():
            db = application.get_db()
            with db.cursor() as cursor:
                cursor.execute("DELETE FROM tbl_user WHERE username IN (%s, %s)", (username, other_username))
                if reference:
                    cursor.execute("DELETE FROM tbl_appointment WHERE reference=%s", (reference,))
                if guest_reference:
                    cursor.execute("DELETE FROM tbl_appointment WHERE reference=%s", (guest_reference,))
            db.commit()
