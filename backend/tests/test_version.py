"""
Tests for GET /api/version endpoint and the APP_VERSION constant.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """Minimal TestClient with external dependencies mocked out."""
    from main import app

    with patch("capture.live_capture.is_capturing", return_value=False), \
         patch("capture.live_capture.get_active_interface", return_value=""), \
         patch("capture.live_capture.get_interfaces", return_value=[]):
        with TestClient(app) as c:
            yield c


# ── GET /api/version ──────────────────────────────────────────────────────────

class TestVersionEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/version")
        assert resp.status_code == 200

    def test_response_contains_version_key(self, client):
        data = client.get("/api/version").json()
        assert "version" in data

    def test_version_is_string(self, client):
        data = client.get("/api/version").json()
        assert isinstance(data["version"], str)

    def test_version_is_not_empty(self, client):
        data = client.get("/api/version").json()
        assert data["version"].strip() != ""

    def test_version_looks_like_semver(self, client):
        """Loose semver check: at least two dots, all digit-separated segments."""
        version = client.get("/api/version").json()["version"]
        parts = version.lstrip("v").split(".")
        assert len(parts) >= 2, f"Expected at least 2 version segments, got: {version}"
        for part in parts:
            assert part.isdigit(), f"Non-numeric segment '{part}' in version '{version}'"

    def test_version_matches_app_constant(self, client):
        """The endpoint should return exactly the APP_VERSION constant."""
        import api.routes as routes_module
        data = client.get("/api/version").json()
        assert data["version"] == routes_module.APP_VERSION

    def test_version_change_is_reflected(self, client):
        """If APP_VERSION is patched, the endpoint reflects the new value."""
        import api.routes as routes_module
        original = routes_module.APP_VERSION
        try:
            routes_module.APP_VERSION = "9.9.9"
            data = client.get("/api/version").json()
            assert data["version"] == "9.9.9"
        finally:
            routes_module.APP_VERSION = original


# ── APP_VERSION constant ──────────────────────────────────────────────────────

class TestAppVersionConstant:
    def test_app_version_defined(self):
        from api.routes import APP_VERSION
        assert APP_VERSION is not None

    def test_app_version_is_str(self):
        from api.routes import APP_VERSION
        assert isinstance(APP_VERSION, str)

    def test_app_version_matches_fastapi_metadata(self):
        """The routes constant should match the version set in main.py."""
        from main import app
        from api.routes import APP_VERSION
        assert app.version == APP_VERSION
