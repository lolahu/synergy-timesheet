from pathlib import Path

from django.test import SimpleTestCase

from config.env import database_config, env_bool, env_csv, media_root


class EnvSettingsHelperTests(SimpleTestCase):
    def test_database_url_config_uses_postgresql(self):
        config = database_config(
            Path("/app/backend"),
            {
                "DATABASE_URL": "postgres://dbuser:secret@example.internal:5432/synergy",
                "DATABASE_CONN_MAX_AGE": "123",
            },
        )

        default = config["default"]
        self.assertEqual(default["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(default["NAME"], "synergy")
        self.assertEqual(default["USER"], "dbuser")
        self.assertEqual(default["PASSWORD"], "secret")
        self.assertEqual(default["HOST"], "example.internal")
        self.assertEqual(default["PORT"], 5432)
        self.assertEqual(default["CONN_MAX_AGE"], 123)

    def test_db_name_config_is_still_supported(self):
        config = database_config(
            Path("/app/backend"),
            {
                "DB_NAME": "synergy",
                "DB_USER": "dbuser",
                "DB_PASSWORD": "secret",
                "DB_HOST": "localhost",
            },
        )

        default = config["default"]
        self.assertEqual(default["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(default["NAME"], "synergy")
        self.assertEqual(default["PORT"], "5432")

    def test_database_config_falls_back_to_sqlite(self):
        base_dir = Path("/app/backend")

        config = database_config(base_dir, {})

        self.assertEqual(config["default"]["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(config["default"]["NAME"], base_dir / "db.sqlite3")

    def test_media_root_uses_env_value_when_provided(self):
        self.assertEqual(
            media_root(Path("/app/backend"), {"MEDIA_ROOT": "/app/media"}),
            Path("/app/media"),
        )

    def test_media_root_defaults_to_backend_media(self):
        self.assertEqual(
            media_root(Path("/app/backend"), {}),
            Path("/app/backend/media"),
        )

    def test_env_csv_trims_and_drops_empty_values(self):
        self.assertEqual(
            env_csv(
                "ALLOWED_HOSTS",
                environ={"ALLOWED_HOSTS": "example.com, www.example.com, ,localhost"},
            ),
            ["example.com", "www.example.com", "localhost"],
        )

    def test_env_bool_parses_common_true_and_false_values(self):
        self.assertTrue(env_bool("DEBUG", environ={"DEBUG": "true"}))
        self.assertTrue(env_bool("DEBUG", environ={"DEBUG": "1"}))
        self.assertFalse(env_bool("DEBUG", environ={"DEBUG": "false"}))
        self.assertFalse(env_bool("DEBUG", default=False, environ={}))
