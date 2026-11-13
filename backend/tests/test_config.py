"""配置读取（app.core.config）的测试。"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Config, get_config

ALL_ENV_KEYS = [
    "LLM_BACKEND",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "RETRIEVAL_BACKEND",
    "RAGFLOW_BASE_URL",
    "RAGFLOW_API_KEY",
    "DATA_DIR",
]

# backend/ 目录：配置里的默认路径必须锚在它下面，不能随进程 cwd 漂移
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """默认值测试不受宿主环境变量干扰。"""
    for key in ALL_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_config_defaults():
    cfg = get_config()
    assert cfg.llm_backend == "online"
    assert cfg.retrieval_backend == "local"
    assert cfg.llm_base_url == ""
    assert cfg.llm_api_key == ""
    assert cfg.llm_model == ""
    assert cfg.ragflow_base_url == ""
    assert cfg.ragflow_api_key == ""
    assert cfg.data_dir == BACKEND_ROOT / "data"


@pytest.mark.parametrize("backend", ["local", "ragflow"])
def test_config_accepts_documented_retrieval_backends(monkeypatch, backend):
    monkeypatch.setenv("RETRIEVAL_BACKEND", backend)
    assert get_config().retrieval_backend == backend


@pytest.mark.parametrize("backend", ["online", "local"])
def test_config_accepts_documented_llm_backends(monkeypatch, backend):
    monkeypatch.setenv("LLM_BACKEND", backend)
    assert get_config().llm_backend == backend


@pytest.mark.parametrize("value", ["cloud", "bge-m3", ""])
def test_config_rejects_unknown_retrieval_backend(monkeypatch, value):
    monkeypatch.setenv("RETRIEVAL_BACKEND", value)
    with pytest.raises(ValidationError):
        get_config()


@pytest.mark.parametrize("value", ["gpt", "dashscope", ""])
def test_config_rejects_unknown_llm_backend(monkeypatch, value):
    monkeypatch.setenv("LLM_BACKEND", value)
    with pytest.raises(ValidationError):
        get_config()


def test_config_reads_environment_variables(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setenv("DATA_DIR", "d:/redtrace/data")
    cfg = Config()
    assert cfg.llm_model == "deepseek-chat"
    assert cfg.llm_base_url == "https://api.example.com/v1"
    assert cfg.data_dir == Path("d:/redtrace/data")


def test_config_data_dir_default_is_absolute():
    """默认值必须是绝对路径：阶段一/二的语料与索引路径靠它定位。"""
    assert get_config().data_dir.is_absolute()


def test_config_data_dir_independent_of_cwd(monkeypatch, tmp_path):
    """从仓库根启动 uvicorn 时，data_dir 仍指向 backend/data，不是不存在的 ./data。"""
    monkeypatch.chdir(tmp_path)
    assert get_config().data_dir == BACKEND_ROOT / "data"


def test_config_env_file_is_absolute():
    """.env 也要锚在 backend/ 下，否则换个 cwd 就静默读不到配置。"""
    raw = Config.model_config["env_file"]
    paths = raw if isinstance(raw, (list, tuple)) else [raw]
    assert paths, "env_file 不能为空"
    assert all(Path(p).is_absolute() for p in paths)
    assert any(Path(p).parent == BACKEND_ROOT for p in paths)
