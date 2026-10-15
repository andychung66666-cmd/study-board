import pytest
from fastapi.testclient import TestClient

from talkboard.config import Settings
from talkboard.server import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(
        create_app(Settings(data_dir=tmp_path)), base_url="http://127.0.0.1:8765"
    )


def test_requests_for_other_host_names_are_refused(client):
    """Blocks DNS rebinding: a hostile site pointed at 127.0.0.1 sends its own Host."""
    response = client.get("/api/health", headers={"host": "evil.example"})
    assert response.status_code == 400


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:8765", "localhost"])
def test_requests_for_localhost_names_are_served(client, host):
    assert client.get("/api/health", headers={"host": host}).status_code == 200


@pytest.mark.parametrize("method, path", [
    ("POST", "/api/talks/1/stop"),
    ("PUT", "/api/talks/1/chunks/0"),
    ("POST", "/api/talks"),
])
def test_cross_site_writes_are_refused_before_anything_happens(client, method, path):
    response = client.request(method, path, headers={"origin": "https://evil.example"})
    assert response.status_code == 403


def test_writes_from_the_apps_own_page_are_allowed(client):
    response = client.post(
        "/api/talks/999/stop", headers={"origin": "http://127.0.0.1:8765"}
    )
    assert response.status_code == 404  # reaches the route: unknown talk


def test_cross_site_reads_are_not_blocked_by_origin(client):
    """Browsers already stop other sites reading the reply; the Host check covers rebinding."""
    response = client.get("/api/health", headers={"origin": "https://evil.example"})
    assert response.status_code == 200
