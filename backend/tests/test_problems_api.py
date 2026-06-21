from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

def test_api_get_problems() -> None:
    response = client.get("/api/problems")
    
    assert response.status_code == 200
    assert response.json() == []