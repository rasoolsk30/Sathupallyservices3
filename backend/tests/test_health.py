from __future__ import annotations


def test_health_ok(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_openapi_available(client):
    resp = client.get("/api/v1/openapi.json")
    assert resp.status_code == 200
    assert "/api/v1/auth/login" in resp.json()["paths"]


def test_unknown_route_error_envelope(client):
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
