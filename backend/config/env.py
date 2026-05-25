import os
from pathlib import Path

import dj_database_url


def env_bool(name, default=False, environ=None):
    if environ is None:
        environ = os.environ
    value = environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_csv(name, default="", environ=None):
    if environ is None:
        environ = os.environ
    value = environ.get(name, default)
    return [item.strip() for item in value.split(",") if item.strip()]


def media_root(base_dir, environ=None):
    if environ is None:
        environ = os.environ
    configured = environ.get("MEDIA_ROOT")
    if configured:
        return Path(configured)
    return base_dir / "media"


def database_config(base_dir, environ=None):
    if environ is None:
        environ = os.environ
    database_url = environ.get("DATABASE_URL")
    if database_url:
        conn_max_age = int(environ.get("DATABASE_CONN_MAX_AGE", "600"))
        return {
            "default": dj_database_url.parse(
                database_url,
                conn_max_age=conn_max_age,
            )
        }

    if environ.get("DB_NAME"):
        return {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": environ.get("DB_NAME"),
                "USER": environ.get("DB_USER"),
                "PASSWORD": environ.get("DB_PASSWORD"),
                "HOST": environ.get("DB_HOST"),
                "PORT": environ.get("DB_PORT", "5432"),
            }
        }

    return {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": base_dir / "db.sqlite3",
        }
    }
