"""Paw & Kin: the CSC312 Flask / MySQL veterinary appointment application."""

import os
import re
import secrets
from collections import OrderedDict
from datetime import datetime, timedelta
from threading import Lock
from time import monotonic
from zoneinfo import ZoneInfo

import pymysql
from dotenv import load_dotenv
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

from db_setup import mysql_tls_options, register_db_commands

load_dotenv()

SERVICES = {
    "consultation": "Vet consultation",
    "vaccination": "Vaccinations",
    "wellness": "Wellness check",
    "grooming": "Grooming & care",
}
SPECIES = ("Dog", "Cat", "Rabbit", "Bird", "Other")
TIMES = tuple(f"{hour:02d}:{minute:02d}" for hour in range(9, 17) for minute in (0, 30))
CLINIC_TIMEZONE = ZoneInfo("Africa/Lagos")
csrf = CSRFProtect()
DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_hex(32))


def clinic_now():
    return datetime.now(CLINIC_TIMEZONE)


def rollback_if_connected():
    """A dropped connection may also refuse rollback; retain the useful form error."""
    if "db" in g:
        try:
            g.db.rollback()
        except pymysql.MySQLError:
            pass


def get_db():
    """Open one MySQL connection per request; never put credentials in code."""
    if "db" not in g:
        g.db = pymysql.connect(
            host=os.getenv("MYSQL_HOST", "127.0.0.1"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            user=os.getenv("MYSQL_USER", "pawkin"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DATABASE", "pawkin"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=5,
            read_timeout=5,
            write_timeout=5,
            autocommit=False,
            **mysql_tls_options(),
        )
    return g.db


def create_app(test_config=None):
    app = Flask(__name__, static_folder="public/static", static_url_path="/static")
    # Set SECRET_KEY to keep sessions valid across restarts.
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
        MAX_CONTENT_LENGTH=32 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        WTF_CSRF_TIME_LIMIT=3600,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        AUTH_RATE_LIMIT=10,
        AUTH_RATE_WINDOW=60,
    )
    if test_config:
        app.config.update(test_config)
    csrf.init_app(app)
    auth_attempts = OrderedDict()
    auth_lock = Lock()

    @app.before_request
    def load_user_and_limit_auth():
        g.user = None
        if request.method == "POST" and request.endpoint in {"login", "signup"}:
            key = (request.endpoint, request.remote_addr)
            now = monotonic()
            with auth_lock:
                count, expires = auth_attempts.get(key, (0, now + app.config["AUTH_RATE_WINDOW"]))
                if expires <= now:
                    count, expires = 0, now + app.config["AUTH_RATE_WINDOW"]
                if count >= app.config["AUTH_RATE_LIMIT"]:
                    return render_template(
                        "error.html", title="Let’s take a short pause.",
                        message="Too many attempts. Wait a minute, then try again.",
                        destination=request.endpoint, action="Back to the form",
                    ), 429, {"Retry-After": str(max(1, int(expires - now) + 1))}
                auth_attempts[key] = (count + 1, expires)
                auth_attempts.move_to_end(key)
                if len(auth_attempts) > 4096:
                    auth_attempts.popitem(last=False)

        user_id = session.get("user_id")
        if user_id is None or request.endpoint in {"static", "logout"}:
            return
        if type(user_id) is not int or user_id <= 0:
            session.clear()
            return
        try:
            with get_db().cursor() as cursor:
                cursor.execute("SELECT id, username FROM tbl_user WHERE id=%s", (user_id,))
                g.user = cursor.fetchone()
        except pymysql.MySQLError:
            app.logger.error("MySQL unavailable while loading account")
            return render_template(
                "error.html", title="Your account is taking a moment.",
                message="We couldn’t connect to your account. Please try again shortly.",
                destination="index", action="Try again",
            ), 503
        if g.user is None:
            session.clear()

    @app.teardown_appcontext
    def close_db(error=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; font-src 'self'; object-src 'none'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        if request.endpoint not in {"index", "static"}:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.context_processor
    def shared_context():
        return {"services": SERVICES, "year": clinic_now().year, "current_user": g.get("user")}

    def next_endpoint():
        # Accept named local destinations only, never a user-provided URL.
        target = request.values.get("next", "book")
        return target if target in {"book", "appointments"} else "book"

    def sign_in(user_id):
        # Discard any old identity, receipt and CSRF token before changing users.
        session.clear()
        session["user_id"] = user_id
        session.permanent = True

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
        if g.user:
            return redirect(url_for("appointments"))
        errors = {}
        username = ""
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not re.fullmatch(r"[A-Za-z0-9_.-]{3,50}", username):
                errors["username"] = "Use 3–50 letters, numbers, dots, hyphens or underscores."
            if not 8 <= len(password) <= 128:
                errors["password"] = "Choose a password between 8 and 128 characters."
            if not errors:
                try:
                    db = get_db()
                    with db.cursor() as cursor:
                        cursor.execute(
                            "INSERT INTO tbl_user (username, password) VALUES (%s, %s)",
                            (username, generate_password_hash(password)),
                        )
                        user_id = cursor.lastrowid
                    db.commit()
                except pymysql.IntegrityError as exc:
                    rollback_if_connected()
                    if exc.args[0] == 1062:
                        errors["username"] = "That username is already taken. Please choose another."
                    else:
                        app.logger.error("Signup database integrity failure (%s)", exc.args[0])
                        errors["form"] = "We couldn’t create your account. Please try again."
                except pymysql.MySQLError:
                    rollback_if_connected()
                    app.logger.error("MySQL unavailable during signup")
                    errors["form"] = "We couldn’t save your account right now. Please try again shortly."
                    return render_template("signup.html", errors=errors, username=username), 503
                else:
                    sign_in(user_id)
                    flash("Your account is created and you’re signed in. Your next bookings will be saved to your account.", "success")
                    return redirect(url_for(next_endpoint()), code=303)
            return render_template("signup.html", errors=errors, username=username, next_endpoint=next_endpoint()), 422
        return render_template("signup.html", errors=errors, username=username, next_endpoint=next_endpoint())

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if g.user:
            return redirect(url_for("appointments"))
        errors = {}
        username = ""
        status = 200
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not 1 <= len(username) <= 50 or not 1 <= len(password) <= 128:
                errors["form"] = "Enter your username and password."
                status = 422
            else:
                try:
                    with get_db().cursor() as cursor:
                        cursor.execute("SELECT id, password FROM tbl_user WHERE username=%s", (username,))
                        user = cursor.fetchone()
                except pymysql.MySQLError:
                    app.logger.error("MySQL unavailable during login")
                    errors["form"] = "We couldn’t sign you in right now. Please try again shortly."
                    status = 503
                else:
                    valid = check_password_hash(user["password"] if user else DUMMY_PASSWORD_HASH, password)
                    if user and valid:
                        sign_in(user["id"])
                        return redirect(url_for(next_endpoint()), code=303)
                    errors["form"] = "That username or password doesn’t match. Please try again."
                    status = 401
        return render_template("login.html", errors=errors, username=username, next_endpoint=next_endpoint()), status

    @app.post("/logout")
    def logout():
        session.clear()
        flash("You’re signed out. See you and your companion soon.", "success")
        return redirect(url_for("index"), code=303)

    @app.get("/appointments")
    def appointments():
        if not g.user:
            return redirect(url_for("login", next="appointments"))
        try:
            with get_db().cursor() as cursor:
                cursor.execute(
                    """SELECT reference, pet_name, species, service, preferred_date,
                              preferred_time, status, notes
                       FROM tbl_appointment WHERE user_id=%s
                       ORDER BY preferred_date DESC, preferred_time DESC, id DESC""",
                    (g.user["id"],),
                )
                bookings = cursor.fetchall()
        except pymysql.MySQLError:
            app.logger.error("MySQL unavailable while loading appointments")
            return render_template("appointments.html", bookings=[], unavailable=True), 503
        for booking in bookings:
            # MySQL returns DATE as date and TIME as timedelta; normalize both
            # for templates and the offline adapter without timezone conversion.
            booking["date_label"] = datetime.strptime(str(booking["preferred_date"]), "%Y-%m-%d").strftime("%a, %d %b %Y")
            parts = str(booking["preferred_time"]).split(":")
            hour = int(parts[0])
            booking["time_label"] = f"{(hour - 1) % 12 + 1}:{parts[1]} {'am' if hour < 12 else 'pm'}"
        return render_template("appointments.html", bookings=bookings, unavailable=False)

    @app.route("/book", methods=["GET", "POST"])
    def book():
        errors = {}
        fields = ("owner_name", "email", "phone", "pet_name", "species", "service", "date", "time", "notes")
        values = {field: "" for field in fields}
        now = clinic_now()
        if request.method == "GET":
            selected = request.args.get("service", "")
            values["service"] = selected if selected in SERVICES else ""
        else:
            values = {field: request.form.get(field, "").strip() for field in fields}
            for field, label, maximum in (
                ("owner_name", "Your name", 100),
                ("pet_name", "Your pet’s name", 80),
            ):
                if not 1 <= len(values[field]) <= maximum:
                    errors[field] = f"{label} is required (up to {maximum} characters)."
            if len(values["email"]) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", values["email"]):
                errors["email"] = "Enter a valid email address."
            digits = re.sub(r"\D", "", values["phone"])
            if not 7 <= len(digits) <= 15 or not re.fullmatch(r"[+()\d\s.-]{7,30}", values["phone"]):
                errors["phone"] = "Enter a valid phone number, including your country code if needed."
            if values["species"] not in SPECIES:
                errors["species"] = "Please choose your pet’s species."
            if values["service"] not in SERVICES:
                errors["service"] = "Please choose a service."
            if values["time"] not in TIMES:
                errors["time"] = "Choose a time between 9:00 am and 4:30 pm."
            try:
                preferred_date = datetime.strptime(values["date"], "%Y-%m-%d").date()
                if preferred_date < now.date():
                    errors["date"] = "Choose today or a future date."
                elif preferred_date.weekday() == 6:
                    errors["date"] = "We’re closed on Sundays. Please choose Monday to Saturday."
                elif values["time"] in TIMES:
                    visit = datetime.strptime(f"{values['date']} {values['time']}", "%Y-%m-%d %H:%M").replace(tzinfo=CLINIC_TIMEZONE)
                    if visit <= now:
                        errors["time"] = "That time has passed. Please choose a later time or another day."
            except ValueError:
                errors["date"] = "Please choose a valid date."
            if len(values["notes"]) > 1000:
                errors["notes"] = "Keep your notes to 1,000 characters or fewer."
            if not errors:
                reference = "PK-" + secrets.token_hex(6).upper()
                try:
                    db = get_db()
                    with db.cursor() as cursor:
                        cursor.execute(
                            """INSERT INTO tbl_appointment
                            (reference, user_id, owner_name, email, phone, pet_name, species,
                             service, preferred_date, preferred_time, notes)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (reference, g.user["id"] if g.user else None, values["owner_name"], values["email"], values["phone"],
                             values["pet_name"], values["species"], values["service"],
                             values["date"], values["time"], values["notes"]),
                        )
                    db.commit()
                except pymysql.MySQLError:
                    rollback_if_connected()
                    app.logger.error("MySQL unavailable during appointment submission")
                    errors["form"] = "We couldn’t save your request right now. Your details are still here; please try again shortly."
                    return render_booking(values, errors, now, 503)
                # Store a receipt in the signed session, without contact details.
                session["receipt"] = {
                    "reference": reference,
                    "user_id": g.user["id"] if g.user else None,
                    "service": SERVICES[values["service"]],
                    "date": preferred_date.strftime("%A, %d %B %Y"),
                    "time": datetime.strptime(values["time"], "%H:%M").strftime("%I:%M %p").lstrip("0"),
                }
                return redirect(url_for("booking_received"), code=303)
            return render_booking(values, errors, now, 422)
        return render_booking(values, errors, now)

    def render_booking(values, errors, now, status=200):
        return render_template(
            "booking.html", values=values, errors=errors, species=SPECIES,
            times=TIMES, today=now.date().isoformat(),
        ), status

    @app.get("/booking/received")
    def booking_received():
        receipt = session.get("receipt")
        if not receipt or receipt.get("user_id") != session.get("user_id"):
            return redirect(url_for("book"))
        return render_template("confirmation.html", receipt=receipt)

    @app.errorhandler(CSRFError)
    def expired_form(error):
        return render_template(
            "error.html", title="Let’s refresh that form.",
            message="Your form has expired or could not be verified. Open a fresh form and try again.",
            destination={"/signup": "signup", "/login": "login", "/logout": "appointments"}.get(request.path, "book"),
            action="Open a fresh form",
        ), 400

    @app.errorhandler(404)
    def not_found(error):
        return render_template(
            "error.html", title="A little off the beaten path.",
            message="We couldn’t find that page. Let’s get you and your pet back home.",
            destination="index", action="Back to home",
        ), 404

    @app.errorhandler(413)
    def too_large(error):
        return render_template(
            "error.html", title="A little too much detail.",
            message="That submission was too large. Please open a fresh form and use shorter details.",
            destination="book", action="Back to booking",
        ), 413

    register_db_commands(app, get_db)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
