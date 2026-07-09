from app.config import Settings


def test_relative_sqlite_database_url_is_resolved_from_project_root(monkeypatch):
    monkeypatch.setenv("ECOM_DB_URL", "sqlite:///backend/data/ecommerce.db")

    settings = Settings()

    assert settings.database_url.startswith("sqlite:////")
    assert settings.database_url.endswith("backend/data/ecommerce.db")
