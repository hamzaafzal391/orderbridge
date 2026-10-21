import pytest
from pydantic import ValidationError

from app.config import DatabaseSettings, Settings
from app.db.session import DatabaseNotConfiguredError, engine_from_settings


def make_settings(**extra: str) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        erpnext_base_url="http://erpnext.test",
        erpnext_api_key="test-key",
        erpnext_api_secret="test-secret",
        ghl_api_token="test-ghl-token",
        **extra,
    )


def test_the_database_is_optional_for_the_main_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert make_settings().database_url is None


def test_database_settings_read_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///example.db")

    settings = DatabaseSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.database_url.get_secret_value() == "sqlite:///example.db"


def test_database_settings_require_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError):
        DatabaseSettings(_env_file=None)  # type: ignore[call-arg]


def test_the_url_is_never_shown_when_printed() -> None:
    settings = make_settings(database_url="postgresql+psycopg://user:SECRET-PASSWORD@localhost/db")

    assert "SECRET-PASSWORD" not in repr(settings)
    assert "SECRET-PASSWORD" not in str(settings)


def test_no_url_means_no_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(DatabaseNotConfiguredError):
        engine_from_settings(make_settings())


def test_an_engine_is_built_from_the_url(tmp_path) -> None:
    engine = engine_from_settings(make_settings(database_url=f"sqlite:///{tmp_path / 'x.db'}"))

    assert engine.dialect.name == "sqlite"
