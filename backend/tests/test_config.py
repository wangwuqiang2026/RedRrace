"""配置读取（app.core.config）的测试。"""

from pathlib import Path

import pytest
from helpers import CONFIG_ENV_KEYS
from pydantic import ValidationError

from app.core.config import Config, get_config

# backend/ 目录：配置里的默认路径必须锚在它下面，不能随进程 cwd 漂移
BACKEND_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """默认值测试不受宿主环境变量干扰。"""
    for key in CONFIG_ENV_KEYS:
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


@pytest.mark.parametrize("value", ["cloud", "bge-m3"])
def test_config_rejects_unknown_retrieval_backend(monkeypatch, value):
    monkeypatch.setenv("RETRIEVAL_BACKEND", value)
    with pytest.raises(ValidationError):
        get_config()


@pytest.mark.parametrize("value", ["gpt", "dashscope"])
def test_config_rejects_unknown_llm_backend(monkeypatch, value):
    monkeypatch.setenv("LLM_BACKEND", value)
    with pytest.raises(ValidationError):
        get_config()


# C-2 带来的口径变更：留空 = 不填，回落默认值而不是报错。
# 原用例把「空串必须 ValidationError」固化成了期望，而那正是「照 .env.example 复制即崩」的根因，
# 故改为断言回落默认，并另立一条把「空格不算留空」的边界钉住。
@pytest.mark.parametrize(
    "key,default", [("RETRIEVAL_BACKEND", "local"), ("LLM_BACKEND", "online")]
)
def test_config_empty_env_value_falls_back_to_default(monkeypatch, key, default):
    monkeypatch.setenv(key, "")
    assert getattr(get_config(), key.lower()) == default


@pytest.mark.parametrize("key", ["RETRIEVAL_BACKEND", "LLM_BACKEND"])
def test_config_whitespace_env_value_is_not_treated_as_empty(monkeypatch, key):
    """只留空格不是「留空」，仍应报错，避免把笔误静默当成默认配置。"""
    monkeypatch.setenv(key, " ")
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


def test_config_accepts_env_example_copied_verbatim(tmp_path):
    """C-2：按 .env.example 首行指引「复制为 .env」必须能跑，留空的枚举键回落默认值。

    .env.example 的本意是让不填的键留空；若空串被当成已提供的值，Literal 字段会直接炸，
    每个人第一天的 `cp .env.example .env` 都会让 get_config() 报错、/api/health 500。
    """
    env = tmp_path / ".env"
    env.write_bytes((BACKEND_ROOT / ".env.example").read_bytes())
    cfg = Config(_env_file=env)
    assert cfg.llm_backend == "online"
    assert cfg.retrieval_backend == "local"
    assert cfg.llm_api_key == ""


def test_config_reads_env_file_with_bom(tmp_path):
    """I-4：Windows 记事本另存 .env 默认带 BOM，不能让首个键被静默吞掉。"""
    env = tmp_path / ".env"
    env.write_bytes("\ufeffRETRIEVAL_BACKEND=ragflow\nLLM_MODEL=bge-m3\n".encode("utf-8"))
    cfg = Config(_env_file=env)
    assert cfg.retrieval_backend == "ragflow"
    assert cfg.llm_model == "bge-m3"
