# Paw & Kin

A Flask and MySQL vet store website for the MIVA CSC312 assessment. The signup page fulfils the assessment’s username/password requirement and the customer form requests an appointment.

The interface uses white, black, soft neutral surfaces, locally hosted Bootstrap, and family-and-pet photography. All required PDF submission files are present.

## Run locally

Requires Python 3.11+ and a local MySQL server.

For an existing local setup, start the application with:

```sh
.venv/bin/python -m flask --app app run --host 127.0.0.1 --port 5001
```

Open **http://127.0.0.1:5001**. For first-time setup, follow the steps below.

### Starting from a fresh copy

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env`: choose your own `MYSQL_PASSWORD`, and generate a secret key with:

```sh
python3 -c 'import secrets; print(secrets.token_hex(32))'
```

Paste that value into `SECRET_KEY`. Then use the startup commands above. Keep `.env` local; it is excluded by `.gitignore`.

`requirements.lock` records the exact runtime and test dependency versions used for local verification. Use `pip install -r requirements.lock` instead if you want those same resolved versions.

### Create the local database and tables

If MySQL is missing, install and start the native Homebrew service:

```sh
brew install mysql
brew services start mysql
```

If MySQL is already installed another way, start that installation and skip those commands. Then, from this project’s folder:

```sh
.venv/bin/python -m flask --app app setup-db
.venv/bin/python -m flask --app app run --host 127.0.0.1 --port 5001
```

`setup-db` prompts privately for the MySQL administrator password (root by default). For a fresh Homebrew installation, press Enter if the root password is blank. This is separate from the application’s `MYSQL_PASSWORD` in `.env`.

### Using an existing MySQL installation

Create a database and an application user with privileges on that database. Set `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, and `MYSQL_PASSWORD` in `.env` to match it, then run:

```sh
.venv/bin/python -m flask --app app init-db
.venv/bin/python -m flask --app app run --host 127.0.0.1 --port 5001
```

Alternatively, execute `schema.sql` in the selected database through your MySQL client. The script creates tables, so the database itself must already exist. The application uses MySQL exclusively.

## Pages and behaviour

| URL | Behaviour |
| --- | --- |
| `/` | Homepage, services, story, visit details, and expandable questions |
| `/signup` | Create an account and sign in automatically; passwords are stored as scrypt hashes |
| `/login` | Sign in with an existing username and password |
| `/logout` | Sign out through a CSRF-protected POST |
| `/appointments` | View appointments belonging to the signed-in account |
| `/book` | Request a visit as a guest or save it to the signed-in account |
| `/book?service=grooming` | Booking form with a service selected; service cards use this pattern |
| `/booking/received` | Receipt for the current browser’s successful request; redirects to booking without a receipt |

Bookings are **requests awaiting manual confirmation**. A reference is shown only after a database commit succeeds. The app does not send email or SMS, confirm availability, or provide an administrative scheduling interface. Saved requests are available in `tbl_appointment` for the clinic to review through MySQL. Multiple requests may ask for the same preferred time.

Signed-in bookings are linked to the account through `tbl_appointment.user_id`. Guest bookings keep an empty user ID. Earlier guest requests are not automatically added when an account is created.

All state-changing forms have CSRF protection. All database writes use parameterized SQL. Invalid submissions show a linked error summary and field-level messages; booking details remain populated. Passwords are never repopulated. Database failures show a retry message instead of claiming a successful save. Refreshing the receipt does not submit the request again.

## Assessment submission map

| PDF requirement | Files |
| --- | --- |
| Flask setup and initialization | `app.py`, `requirements.txt` |
| HTML / Bootstrap homepage in templates | `templates/index.html`, `templates/base.html`, `static/vendor/bootstrap.min.css` |
| Signup with username/password and `request.form` validation | `templates/signup.html`, `app.py` |
| MySQL connection and `tbl_user` | `app.py`, `schema.sql`, `.env.example` |
| Hash passwords before storing them | `generate_password_hash()` in `app.py` |
| Appointment booking extension | `templates/booking.html`, `templates/confirmation.html`, `tbl_appointment` in `schema.sql` |


## Tests

```sh
MYSQL_INTEGRATION=1 .venv/bin/python -m pytest -q
```

Observed result:
```
...................................................................             [100%]
67 passed in 10.33s
```

To run the opt-in MySQL test separately, run these test commands:

```sh
.venv/bin/python -m pytest -q
MYSQL_INTEGRATION=1 .venv/bin/python -m pytest -q tests/test_mysql.py
```

Coverage includes successful and failed login, logout, password hashing, CSRF rotation, attempt limits, guest bookings, forged owner IDs, isolation between users, database failures, and setup/upgrade decisions. The MySQL test now checks the account/booking link and login flow against a real database.
