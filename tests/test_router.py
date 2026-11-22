from unittest.mock import MagicMock

import pytest

from src.agents.router import QueryRouter


@pytest.mark.parametrize("classification,expected", [
    ("SMALL_TALK", "SMALL_TALK"), (" SUMMARIZATION ", "SUMMARIZATION"),
    ("DIRECT_KNOWLEDGE", "DIRECT_KNOWLEDGE"), ("WEB_SEARCH", "WEB_SEARCH"),
    ("I am not sure.", "DIRECT_KNOWLEDGE"),
    ("Not SMALL_TALK; choose WEB_SEARCH", "DIRECT_KNOWLEDGE"),
])
def test_router_accepts_only_exact_categories(classification, expected):
    client = MagicMock()
    client.generate.return_value = {"response": classification}
    assert QueryRouter(client=client).route_query("a query") == expected


def test_router_outage_uses_local_retrieval():
    client = MagicMock()
    client.generate.side_effect = ConnectionError("offline")
    assert QueryRouter(client=client).route_query("a query") == "DIRECT_KNOWLEDGE"
