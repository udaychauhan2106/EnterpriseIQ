import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.persistence.database import get_engine


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    database_url = f"sqlite:///{(tmp_path / 'enterpriseiq-test.db').as_posix()}"
    monkeypatch.setattr(settings, "DATABASE_URL", database_url)
    monkeypatch.setattr(settings, "ENTERPRISEIQ_PROCESSED_DATA_DIR", str(tmp_path / "processed"))
    monkeypatch.setattr(settings, "ENTERPRISEIQ_API_KEY", None)
    monkeypatch.setattr(settings, "ENTERPRISEIQ_ENABLE_EXTERNAL_RETRIEVAL", False)
    get_engine.cache_clear()
    with TestClient(app) as client:
        yield client
    engine = get_engine()
    engine.dispose()
    get_engine.cache_clear()
