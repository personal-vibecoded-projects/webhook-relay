from fastapi.testclient import TestClient

from relay.main import app


def test_health_contract():
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "webhook-relay"}


def test_health_is_read_only():
    with TestClient(app) as client:
        response = client.post("/api/health", json={"status": "offline"})
    assert response.status_code == 405


def test_unimplemented_routes_are_not_successful():
    with TestClient(app) as client:
        response = client.get("/api/events")
    assert response.status_code == 404
