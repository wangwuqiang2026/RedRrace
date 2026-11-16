"""pytest 插件：只提供 fixture 与会话级仓库保护。

测试辅助函数与样例数据在 helpers.py；本文件不被测试模块 import（conftest 是 pytest
插件文件，import 它属反模式）。单测不依赖 backend/data/来源白名单.yml 是否存在，
一律用 tmp_path 自造白名单。
"""

import os
from pathlib import Path

import pytest
from helpers import write_whitelist

BACKEND_ROOT = Path(__file__).resolve().parents[1]

# 会话期间不许被测试改动的目录，以及其中本就允许增长派生文件的子目录
GUARDED_DIR = BACKEND_ROOT / "data"
GUARDED_EXEMPT = {"raw", "parsed", "index", "exports", "__pycache__", ".pytest_cache", ".ruff_cache"}


def dir_state(base: Path) -> dict[str, tuple[int, int]]:
    """目录下每个受管文件的 (大小, mtime_ns) 指纹，用于比对有没有被写脏。"""
    if not base.is_dir():
        return {}
    state = {}
    for path in base.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(base)
        if set(rel.parts) & GUARDED_EXEMPT:
            continue
        stat = path.stat()
        state[str(rel)] = (stat.st_size, stat.st_mtime_ns)
    return state


@pytest.fixture(scope="session")
def data_snapshot() -> dict[str, tuple[int, int]]:
    """会话开始时的项目数据目录指纹，供用例断言「跑测试没有改过它」。"""
    return dir_state(GUARDED_DIR)


@pytest.fixture(scope="session", autouse=True)
def isolate_write_targets(tmp_path_factory):
    """把 `DATA_DIR` 指到会话临时目录。

    审查 C2 的根因修复：`extract._default_backlog_path()`、`save_parsed()`、
    `migrate.default_db_path()` 都跟着 `Config.data_dir`，所以任何「不传路径的默认写盘」
    在测试会话里一律落在临时目录，绝不可能再往 `backend/data/` 追加 fixture 噪声。
    """
    sandbox = tmp_path_factory.mktemp("redtrace-data-sandbox")
    previous = os.environ.get("DATA_DIR")
    os.environ["DATA_DIR"] = str(sandbox)
    yield sandbox
    if previous is None:
        os.environ.pop("DATA_DIR", None)
    else:
        os.environ["DATA_DIR"] = previous


@pytest.fixture(scope="session", autouse=True)
def isolate_dotenv():
    """测试会话一律不读 `backend/.env`。

    根因（2026-11-16 实测）：`Config` 的 `env_file` 固化指向 `backend/.env`。部署时按运行手册
    把真实 key 填进去之后，`test_config_defaults` 与两条「缺配置必须大声报错」的用例一起转红——
    它们隐含依赖「仓库里没有 .env」这一脆弱前提，而可交付的部署恰恰要求它有 key。
    本机配置不该改变被测语义，所以整套件默认屏蔽 .env；需要 .env 行为的用例一律显式
    `Config(_env_file=...)` 自造文件（`test_config.py` 现有两个用例已是这种写法）。
    """
    from app.core.config import ENV_FILE, Config

    Config.model_config["env_file"] = None
    try:
        yield
    finally:
        Config.model_config["env_file"] = ENV_FILE


@pytest.fixture(scope="session", autouse=True)
def guard_project_directory(data_snapshot, isolate_write_targets):
    """会话结束再核一次：谁要是绕过了隔离把文件写进项目目录，整套件直接失败。"""
    yield
    changed = dir_state(GUARDED_DIR)
    diff = sorted(k for k in set(data_snapshot) | set(changed) if data_snapshot.get(k) != changed.get(k))
    if diff:
        raise AssertionError(f"测试改动或新建了项目目录文件：{diff}")


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
