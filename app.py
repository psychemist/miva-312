"""Paw & Kin: the CSC312 Flask / MySQL veterinary appointment application."""

import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import click
import pymysql
from dotenv import load_dotenv
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.security import generate_password_hash

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
        )
    return g.db


def create_app(test_config=None):
    app = Flask(__name__)
    # A generated local key permits a first run without shipping a shared secret.
    # Set SECRET_KEY in .env to keep sessions valid across processes/restarts.
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
        MAX_CONTENT_LENGTH=32 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE", "false").lower() == "true",
        WTF_CSRF_TIME_LIMIT=3600,
    )
    if test_config:
        app.config.update(test_config)
    csrf.init_app(app)

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
        return {"services": SERVICES, "year": clinic_now().year}

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.route("/signup", methods=["GET", "POST"])
    def signup():
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
                    flash("Your account is created. You can now request your pet’s first visit.", "success")
                    return redirect(url_for("book"), code=303)
            return render_template("signup.html", errors=errors, username=username), 422
        return render_template("signup.html", errors=errors, username=username)

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
                            (reference, owner_name, email, phone, pet_name, species,
                             service, preferred_date, preferred_time, notes)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (reference, values["owner_name"], values["email"], values["phone"],
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
        if not receipt:
            return redirect(url_for("book"))
        return render_template("confirmation.html", receipt=receipt)

    @app.errorhandler(CSRFError)
    def expired_form(error):
        return render_template(
            "error.html", title="Let’s refresh that form.",
            message="Your form has expired or could not be verified. Open a fresh form and try again.",
            destination="signup" if request.path == "/signup" else "book",
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

    @app.cli.command("init-db")
    def init_db():
        """Create required tables in the already configured MySQL database."""
        schema = Path(app.root_path, "schema.sql").read_text()
        try:
            db = get_db()
            with db.cursor() as cursor:
                for statement in schema.split(";"):
                    if statement.strip():
                        cursor.execute(statement)
            db.commit()
        except pymysql.MySQLError as exc:
            raise click.ClickException("Cannot initialize MySQL. Check .env and make sure the database exists.") from exc
        click.echo("MySQL tables ready: tbl_user and tbl_appointment.")

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
