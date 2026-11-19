"""阶段三 T3-4：提示词与 LLM 双实现（plan 步骤 3）。

硬约束：只允许使用给定证据编号；每个结论句用编号标注；证据不足输出「无证据」标记；
不得推断/补充/改写；温度 0；在线与本地双实现按配置切换，换模型不改流水线。
不联网：在线档一律注入 httpx.MockTransport（规范 5.17）。
"""

from __future__ import annotations

import json
import sys

import httpx
import pytest

from app.core.config import Config
from app.qa import constants
from app.qa.evidence import Evidence
from app.qa.llm import LocalQaModel, OnlineQaModel, build_qa_model
from app.qa.prompt import NO_EVIDENCE_MARK, build_prompt
from app.qa.schemas import Locator, SourceOut


def sample_evidence():
    source = SourceOut(
        source_id="S001", title="校史", publisher="人民出版社", publish_date="1985",
        url_or_path="data/raw/articles/S001.html", access_date="2026-11-13",
        license_note="公开", corpus_tier="核心", media_type="文章",
    )
    return [
        Evidence(
            claim_id=1, card_id=1, source_id="S001", subject="某校", predicate="创设时间",
            value="一九二五年", quote="该校于一九二五年创设", score=0.8, source=source,
            locator=Locator(quote="该校于一九二五年创设", heading_path=["沿革"]),
        )
    ]


def qa_cfg(**over):
    base = {
        "llm_backend": "online", "llm_base_url": "https://mock.example/v1",
        "llm_api_key": "sk-test-not-a-real-key", "llm_model": "qwen-test",
        "llm_enable_thinking": False,
    }
    base.update(over)
    return Config(**base)


def test_prompt_contains_numbered_evidence_and_hard_rules():
    prompt = build_prompt("某校何时创设？", sample_evidence())
    assert "[1]" in prompt and "某校" in prompt and "该校于一九二五年创设" in prompt
    assert NO_EVIDENCE_MARK in prompt, "提示词必须写明「无证据」标记（步骤 3）"
    assert "不得推断" in prompt and "不得" in prompt
    assert constants.PROMPT_VERSION in prompt, "提示词版本号必须进提示词并落日志"


def test_prompt_with_no_evidence_says_so():
    prompt = build_prompt("库外人物是谁？", [])
    assert NO_EVIDENCE_MARK in prompt
    assert "没有任何可用证据，禁止作答" in prompt
    assert "来源：" not in prompt, "没有证据却列出带来源的编号会诱导模型编造引用"


def test_online_model_sends_temperature_zero_and_thinking_flag():
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "某校于一九二五年创设[1]。"}}]})

    model = OnlineQaModel(qa_cfg(), transport=httpx.MockTransport(handler))
    draft = model.generate("某校何时创设？", sample_evidence())
    assert draft == "某校于一九二五年创设[1]。"
    body = captured[0]
    assert body["temperature"] == 0
    assert body["enable_thinking"] is False, "扩展项须显式发送（阶段一 A/B 教训）"
    assert body["model"] == "qwen-test"


def test_online_model_reports_missing_config():
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        OnlineQaModel(qa_cfg(llm_api_key=""))


def test_local_model_requires_optional_dependency(monkeypatch):
    """本地档缺依赖显式报错并点名安装命令（与 LocalEmbedder 同纪律，不隐式换档）。"""
    monkeypatch.setitem(sys.modules, "llama_cpp", None)
    with pytest.raises(ImportError, match="llama-cpp-python"):
        LocalQaModel(qa_cfg(llm_backend="local"))


def test_build_qa_model_dispatches_by_config_only():
    assert isinstance(build_qa_model(qa_cfg()), OnlineQaModel)
    with pytest.raises(ImportError):
        build_qa_model(qa_cfg(llm_backend="local"))
