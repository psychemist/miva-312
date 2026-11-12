"""Opt-in tests against a real configured MySQL server; never use the SQLite double."""

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

    def post(path, data):
        html = client.get(path).text
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        return client.post(path, data={**data, "csrf_token": token})

    try:
        response = post("/signup", {"username": username, "password": "integration-passphrase"})
        assert response.status_code == 303
        with app.app_context():
            with application.get_db().cursor() as cursor:
                cursor.execute("SELECT password FROM tbl_user WHERE username=%s", (username,))
                assert check_password_hash(cursor.fetchone()["password"], "integration-passphrase")
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
                cursor.execute("SELECT status, preferred_date FROM tbl_appointment WHERE reference=%s", (reference,))
                row = cursor.fetchone()
                assert row["status"] == "pending"
                assert row["preferred_date"] == future
    finally:
        with app.app_context():
            db = application.get_db()
            with db.cursor() as cursor:
                cursor.execute("DELETE FROM tbl_user WHERE username=%s", (username,))
                if reference:
                    cursor.execute("DELETE FROM tbl_appointment WHERE reference=%s", (reference,))
            db.commit()
