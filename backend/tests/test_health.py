"""健康检查接口的测试（阶段零步骤 1、4）。"""


def test_health_returns_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["retrieval_backend"] == "local"


def test_health_reports_configured_backend(monkeypatch, client):
    """retrieval_backend 取自配置，不是写死的值。"""
    monkeypatch.setenv("RETRIEVAL_BACKEND", "ragflow")
    body = client.get("/api/health").json()
    assert body["retrieval_backend"] == "ragflow"
