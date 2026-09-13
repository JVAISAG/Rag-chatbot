from fastapi.testclient import TestClient
from src.api.main import app, pipeline
from unittest.mock import patch

client = TestClient(app)

@patch.object(pipeline, 'query')
def test_query_endpoint(mock_query):
    # Setup mock return value for query
    mock_query.return_value = ("Test answer", [{"text": "Source 1", "metadata": {"source": "doc1.txt"}}])
    
    response = client.post("/api/v1/query", json={"query": "Hello", "use_hybrid": False})
    
    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Test answer"
    assert len(data["sources"]) == 1
    assert data["sources"][0]["metadata"]["source"] == "doc1.txt"
    mock_query.assert_called_once()

@patch.object(pipeline, 'build_index')
def test_index_endpoint_success(mock_build_index):
    mock_build_index.return_value = True
    
    response = client.post("/api/v1/index")
    
    assert response.status_code == 200
    assert response.json() == {"message": "Index rebuilt successfully."}

@patch.object(pipeline, 'build_index')
def test_index_endpoint_failure(mock_build_index):
    mock_build_index.return_value = False
    
    response = client.post("/api/v1/index")
    
    assert response.status_code == 400
    assert "Failed to build index" in response.json()["detail"]
