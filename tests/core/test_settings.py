"""Settings read from the environment."""

from sqlalchemy.engine import make_url

from claimpilot_core.settings import Settings


def test_the_database_password_from_secrets_manager_goes_into_the_url(monkeypatch):
    monkeypatch.setenv(
        "CLAIMPILOT_DATABASE_URL",
        "postgresql+psycopg://claimpilot@db.internal:5432/claimpilot?sslmode=require",
    )
    monkeypatch.setenv("CLAIMPILOT_DATABASE_PASSWORD", "p@ss:w/rd?#1")  # RDS passwords have symbols
    url = make_url(Settings(_env_file=None).database_url)
    assert (url.username, url.password, url.host) == ("claimpilot", "p@ss:w/rd?#1", "db.internal")
    assert url.query == {"sslmode": "require"}


def test_a_url_with_its_own_password_is_left_alone(monkeypatch):
    monkeypatch.delenv("CLAIMPILOT_DATABASE_PASSWORD", raising=False)
    monkeypatch.setenv("CLAIMPILOT_DATABASE_URL", "postgresql+psycopg://a:b@127.0.0.1:5438/c")
    assert Settings(_env_file=None).database_url == "postgresql+psycopg://a:b@127.0.0.1:5438/c"
