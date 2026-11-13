"""健康检查接口的测试（阶段零步骤 1、4）。"""

import pytest
from helpers import CONFIG_ENV_KEYS


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """宿主若设置了 RETRIEVAL_BACKEND，默认值断言会误报（终审 M-5）。"""
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


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
