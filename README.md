# Paw & Kin

A Flask and MySQL vet store website for the MIVA CSC312 assessment. The main customer form requests an appointment; the separate signup page fulfils the assessment’s username/password requirement.

The interface uses white, black, soft neutral surfaces, locally hosted Bootstrap, and family-and-pet photography. All required PDF submission files are present.

## Run locally

Requires Python 3.11+ and MySQL 8 (or Docker Desktop with Docker Compose).

In this workspace, `.venv` already contains the dependencies and `.env` has generated local credentials. Start Docker Desktop, then run:

```sh
docker compose up -d --wait
.venv/bin/python -m flask --app app init-db
.venv/bin/python -m flask --app app run --host 127.0.0.1 --port 5000
```

Open **http://127.0.0.1:5000**. If port 5000 is occupied, use `--port 5001`.

The database container loads `schema.sql` automatically when its data volume is first created. `init-db` is safe to run again and checks connectivity. Docker Compose loads its database name and credentials from `.env`. Stop the database with `docker compose down`; its named volume retains saved data.

### Starting from a fresh copy

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Edit `.env`: choose your own `MYSQL_PASSWORD`, and generate a secret key with:

```sh
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

Paste that value into `SECRET_KEY`. Then use the startup commands above. Keep `.env` local; it is excluded by `.gitignore`.

`requirements.lock` records the exact runtime and test dependency versions used for local verification. Use `pip install -r requirements.lock` instead if you want those same resolved versions.

### Using an existing MySQL installation

Create a database and an application user with privileges on that database. Set `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, and `MYSQL_PASSWORD` in `.env` to match it, then run:

```sh
.venv/bin/python -m flask --app app init-db
.venv/bin/python -m flask --app app run --host 127.0.0.1 --port 5000
```

Alternatively, execute `schema.sql` in the selected database through your MySQL client. The script creates tables, so the database itself must already exist. The application uses MySQL exclusively.

## Pages and behaviour

| URL | Behaviour |
| --- | --- |
| `/` | Homepage, services, story, visit details, and expandable questions |
| `/signup` | Username/password signup, server validation, duplicate detection, and scrypt password hashing |
| `/book` | Guest appointment request with owner, pet, service, preferred date/time, and optional notes |
| `/book?service=grooming` | Booking form with a service selected; service cards use this pattern |
| `/booking/received` | Receipt for the current browser’s successful request; redirects to booking without a receipt |

Bookings are **requests awaiting manual confirmation**. A reference is shown only after a database commit succeeds. The app does not send email or SMS, confirm availability, or provide an administrative scheduling interface. Saved requests are available in `tbl_appointment` for the clinic to review through MySQL. Multiple requests may ask for the same preferred time.

Signup creates an account record as required by the brief; login and account management are outside this version. Booking works without an account.

Both forms have CSRF protection. All database writes use parameterized SQL. Invalid submissions show a linked error summary and field-level messages; booking details remain populated. Passwords are never repopulated. Database failures show a retry message instead of claiming a successful save. Refreshing the receipt does not submit the request again.

## Content choices to edit

“Paw & Kin” is a working brand. The service list, copy, and **Monday–Saturday, 9am–5pm** opening hours are demo business choices, not information supplied by an existing clinic. Appointment requests use half-hour preferred times from 9am to 4:30pm in **Africa/Lagos / West Africa Time (UTC+1)**. Sundays and times in the past are rejected on the server. Edit the service/time constants and matching page copy together if those choices change.

No clinic address, phone number, prices, reviews, or professional credentials have been invented. Pet essentials are described as available in store; this version does not include online purchases. Photo provenance and the limits of its geographic identification are recorded in [ASSETS.md](ASSETS.md).

## Assessment submission map

| PDF requirement | Files |
| --- | --- |
| Flask setup and initialization | `app.py`, `requirements.txt` |
| HTML / Bootstrap homepage in templates | `templates/index.html`, `templates/base.html`, `static/vendor/bootstrap.min.css` |
| Signup with username/password and `request.form` validation | `templates/signup.html`, `app.py` |
| MySQL connection and `tbl_user` | `app.py`, `schema.sql`, `.env.example` |
| Hash passwords before storing them | `generate_password_hash()` in `app.py` |
| Appointment booking extension | `templates/booking.html`, `templates/confirmation.html`, `tbl_appointment` in `schema.sql` |

Submit the whole source folder so the shared template and static files accompany the explicitly required `app.py`, `index.html`, `signup.html`, and SQL script. Exclude `.env`, `.venv`, `__pycache__`, and `.pytest_cache`.

## Verification

```sh
.venv/bin/python -m pytest -q
.venv/bin/python -m pip check
```

Observed result: **35 passed, 1 skipped**, and **No broken requirements found**. Offline tests use a small SQLite adapter as a transactional MySQL test double; SQLite is not an application backend. They cover saved signup/booking data, password hash verification, duplicate usernames, validation boundaries, SQL/HTML payloads, missing/expired/cross-session CSRF tokens, database failure handling, and receipt refreshes.

After MySQL is running and the schema has been initialized, independently verify the real connector and database with:

```sh
MYSQL_INTEGRATION=1 .venv/bin/python -m pytest -q tests/test_mysql.py
```

This opt-in test creates uniquely named test records and removes them afterwards. It was **not run against a working MySQL server in this workspace**: no server was installed/running, and Docker’s daemon was unavailable. `init-db` failed with `Error: Cannot initialize MySQL. Check .env and make sure the database exists.`

This workspace also refused Flask’s HTTP listener with `Operation not permitted`. Browser checks therefore used HTML rendered by the real Flask routes and served as temporary static previews. Form processing was exercised through Flask’s test client. The browser previews do not establish a successful live HTTP submission or a live MySQL save.

See [evidence/README.md](evidence/README.md) for screenshots, responsive checks, and the booking preview’s Lighthouse report. No remote deployment or Git commit was made.
