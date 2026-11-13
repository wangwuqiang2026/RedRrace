"""pytest 插件文件：只提供 fixture。

测试辅助函数与样例数据在 helpers.py；本文件不被测试模块 import（conftest 是 pytest
插件文件，import 它属反模式）。单测不依赖 backend/data/来源白名单.yml 是否存在，
一律用 tmp_path 自造白名单。
"""

import pytest
from helpers import write_whitelist


@pytest.fixture
def whitelist_file(tmp_path):
    """自造白名单文件（含三条 verified: true 的机构），返回路径。"""
    return write_whitelist(tmp_path)


@pytest.fixture
def client():
    """FastAPI 测试客户端。"""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
