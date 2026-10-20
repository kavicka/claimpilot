"""Settings read from the environment."""

import pytest
from sqlalchemy.engine import make_url

from claimpilot_core.settings import InsecureConfigError, Settings, check_production


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


# --- production fail-fast --------------------------------------------------------------------

GOOD = {
    "environment": "production",
    "database_url": "postgresql+psycopg://claimpilot:S3cret-from-rds@db.internal:5432/claimpilot",
    "pii_vault_key": "k" * 44,
    "session_secret": "s" * 40,
    "intake_token": "t" * 32,
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "DATABASE_URL",
        "DATABASE_PASSWORD",
        "PII_VAULT_KEY",
        "SESSION_SECRET",
        "INTAKE_TOKEN",
        "DEMO_PASSWORD",
        "ENVIRONMENT",
    ):
        monkeypatch.delenv(f"CLAIMPILOT_{name}", raising=False)


def prod(**over) -> Settings:
    return Settings(_env_file=None, **{**GOOD, **over})


def test_the_default_environment_is_dev():
    assert Settings(_env_file=None).environment == "dev"


def test_a_complete_production_config_starts():
    check_production(prod(), "api")
    check_production(prod(session_secret="", intake_token=""), "worker")  # not the worker's secrets


def test_dev_is_never_refused():
    check_production(Settings(_env_file=None, environment="dev"), "api")


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"demo_password": "claimpilot-demo"}, "DEMO_PASSWORD"),
        ({"pii_vault_key": ""}, "VAULT_KEY"),
        ({"session_secret": ""}, "SESSION_SECRET"),
        ({"intake_token": ""}, "INTAKE_TOKEN"),
        (
            {"database_url": "postgresql+psycopg://claimpilot:claimpilot@db:5432/claimpilot"},
            "database password",
        ),
        (
            {"database_url": "postgresql+psycopg://claimpilot@db:5432/claimpilot"},
            "database password",
        ),
    ],
)
def test_production_refuses_dev_leftovers(over, needle):
    with pytest.raises(InsecureConfigError, match=needle):
        check_production(prod(**over), "api")


def test_the_database_password_from_secrets_manager_counts(monkeypatch):
    monkeypatch.setenv("CLAIMPILOT_DATABASE_PASSWORD", "rds-generated-pw")
    check_production(
        prod(database_url="postgresql+psycopg://claimpilot@db.internal:5432/claimpilot"), "api"
    )


def test_the_worker_is_refused_for_the_shared_secrets_too():
    with pytest.raises(InsecureConfigError, match="VAULT_KEY"):
        check_production(prod(pii_vault_key=""), "worker")
    with pytest.raises(InsecureConfigError, match="DEMO_PASSWORD"):
        check_production(prod(demo_password="x"), "worker")
