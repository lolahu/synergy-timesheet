# Synergy Timesheet

Synergy Timesheet is a lightweight internal Django app for construction crew time entry, parking receipt submission, and admin review.

## What It Does

- Foreman/admin weekly timesheet entry by project.
- Worker, project, time entry, and parking entry management in Django Admin.
- Parking cost submission with receipt upload.
- Admin weekly hours dashboard with week and cumulative totals.
- Email/password signup, login, logout, and password reset.
- Production-ready configuration for Railway, PostgreSQL, WhiteNoise static files, and a Railway volume for uploaded receipts.

## App Structure

```text
backend/
  config/              Django project settings, URLs, WSGI/ASGI
  core/                App models, views, admin, templates, tests
  manage.py
docs/
  deploy-railway.md    Railway deployment checklist
  railway-production-readiness-design.md
Procfile              Railway process command
requirements.txt      Python dependencies
```

## Main Routes

- `/` - home menu
- `/signup/` - create an inactive user account pending admin approval
- `/login/` - log in with email/password
- `/password-reset/` - password reset flow
- `/timesheet/` - weekly project timesheet entry
- `/parking/` - parking receipt submission
- `/admin/` - Django Admin
- `/admin/core/timeentry/weekly-dashboard/` - admin weekly hours dashboard

## Roles And Access

Timesheet entry is restricted to users who are either:

- staff/admin users, meaning `User.is_staff = True`
- members of the configured Foreman group

The Foreman group name is configured with:

```text
FOREMAN_GROUP_NAME=Foreman
```

The app checks this group case-insensitively, so `FOREMAN`, `Foreman`, and `foreman` all match.

The Django Admin group permission checkboxes are available, but the custom timesheet page currently uses simple staff-or-Foreman group membership rather than granular `user.has_perm(...)` checks.

## Local Setup

From the repo root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run migrations:

```bash
cd backend
python manage.py migrate
```

Create an admin user:

```bash
python manage.py createsuperuser
```

Start the local server:

```bash
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

## Local Configuration

Local development defaults are intentionally simple:

- `DEBUG=True`
- SQLite database at `backend/db.sqlite3`
- uploaded files under `backend/media`
- static files collected under `backend/staticfiles`

Optional local `.env` values:

```text
SECRET_KEY=local-dev-secret
DEBUG=True
ALLOWED_HOSTS=127.0.0.1,localhost
FOREMAN_GROUP_NAME=Foreman
```

## Production Configuration

The app is prepared for Railway with:

- `DATABASE_URL` support for Railway PostgreSQL
- configurable `MEDIA_ROOT` for a Railway volume
- WhiteNoise static file serving
- production HTTPS and secure-cookie settings
- `Procfile` startup command

Required Railway env vars:

```text
SECRET_KEY=<long-random-secret>
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com,your-service.up.railway.app
CSRF_TRUSTED_ORIGINS=https://yourdomain.com,https://www.yourdomain.com,https://your-service.up.railway.app
DATABASE_URL=<provided-by-railway-postgresql>
MEDIA_ROOT=/app/media
FOREMAN_GROUP_NAME=Foreman
SECURE_SSL_REDIRECT=True
```

The Railway `Procfile` command is:

```text
web: cd backend && ./bin/railway-start.sh
```

That script runs migrations, collects static files, and starts Gunicorn.

See [docs/deploy-railway.md](docs/deploy-railway.md) for the full Railway, PostgreSQL, volume, and GoDaddy checklist.

## Uploaded Receipts

Parking receipts are uploaded through `/parking/` and stored below `MEDIA_ROOT`.

For Railway, mount a volume at:

```text
/app/media
```

and set:

```text
MEDIA_ROOT=/app/media
```

For the first launch, the operating plan is for admins to download receipts weekly and then delete them after confirmation. If receipt storage becomes business-critical, move uploads to S3-compatible object storage later.

## Tests

Run the test suite:

```bash
.venv/bin/python backend/manage.py test core
```

Run Django checks:

```bash
.venv/bin/python backend/manage.py check
```

Check the Railway startup script syntax:

```bash
bash -n backend/bin/railway-start.sh
```

Optional production-style check:

```bash
env DEBUG=False \
  SECRET_KEY=abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOP \
  ALLOWED_HOSTS=example.com \
  CSRF_TRUSTED_ORIGINS=https://example.com \
  MEDIA_ROOT=/app/media \
  .venv/bin/python backend/manage.py check --deploy
```

Django may warn about HSTS until you intentionally enable it after the production domain is stable.
