import pytest
from fastapi.testclient import TestClient

from relay.main import create_app
from relay.security import SecuritySettings


@pytest.mark.parametrize(
    "origin",
    [
        "https://relay.example/path",
        "https://relay.example?x=1",
        "ftp://relay.example",
        "https://relay.example#fragment",
        "https://user@relay.example",
    ],
)
def test_public_origin_rejects_non_origin_values(origin):
    with pytest.raises(ValueError):
        SecuritySettings(public_origin=origin)


def test_insecure_cookies_are_only_available_for_loopback():
    with pytest.raises(ValueError):
        SecuritySettings(public_origin="http://relay.example", allow_http_cookie=True)
    assert SecuritySettings(
        public_origin="http://localhost:5173", allow_http_cookie=True
    ).allow_http_cookie


def test_openapi_contains_authenticated_workspace_routes():
    paths = create_app().openapi()["paths"]
    assert "/api/workspaces/{workspace_id}/ownership" in paths
    assert "/api/invitations/{invitation_id}/accept" in paths


def test_origin_check_runs_before_any_database_write():
    with TestClient(create_app()) as client:
        result = client.post(
            "/api/workspaces", json={"slug": "demo-team", "name": "Team"}
        )
    assert result.status_code == 403
