import pytest

from app.services.retrieval import qdrant_service


def test_qdrant_errors_are_not_returned_as_empty_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class BrokenClient:
        def query_points(self, **_kwargs):
            assert _kwargs
            raise ConnectionError("service unavailable")

    monkeypatch.setattr(qdrant_service, "client", BrokenClient())

    def embed_query(query: str) -> list[float]:
        assert query == "test query"
        return [0.0]

    monkeypatch.setattr(qdrant_service, "embed_query", embed_query)

    with pytest.raises(RuntimeError, match="search failed") as error:
        qdrant_service.search_enterprise_knowledge("test query")

    assert isinstance(error.value.__cause__, ConnectionError)
