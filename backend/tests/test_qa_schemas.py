"""问答契约占位（阶段零F 步骤 2）的测试。

这些字段名与类型一经定死不得漂移：前端类型由 openapi-typescript 从 /openapi.json 生成，
后端改名就会打断前端编译（阶段零F 的契约漂移测试要证明的正是这件事）。
"""

import dataclasses
import json
from typing import Literal

import pytest
from helpers import VALID_ROW
from pydantic import ValidationError

from app.ingestion.registry import SourceRecord
from app.main import app
from app.qa import constants as qa_constants
from app.qa.schemas import (
    AnswerOut,
    AskRequest,
    Citation,
    ConflictItem,
    Locator,
    SourceOut,
)

# SourceOut 在九字段之外新增的白名单三字段（口径来自 registry.Whitelist.entries）
WHITELIST_FIELDS = {"domain", "sections", "verified"}


def make_source_out(**overrides):
    payload = {
        "source_id": "S001",
        "title": "红色文化读本（第三卷）",
        "publisher": "人民出版社",
        "publish_date": "1985",
        "url_or_path": "data/raw/ebook_001.pdf",
        "access_date": "2026-11-13",
        "license_note": "公开出版物",
        "corpus_tier": "核心",
        "media_type": "电子书",
    }
    payload.update(overrides)
    return SourceOut(**payload)


def make_citation(index=1, source_id="S001", quote="该地于一九四九年四月解放"):
    return Citation(
        index=index,
        claim="解放时间",
        locator=Locator(page=3, paragraph=None, heading_path=["第三章", "解放"], quote=quote),
        source=make_source_out(source_id=source_id),
    )


def answer_payload():
    """一份字段齐全的 AnswerOut 入参（I2 的必填断言靠删它的键来构造）。"""
    return {
        "refusal": False,
        "refusal_reason": None,
        "answer": "根据登记的来源，该地于一九四九年四月解放。",
        "citations": [],
        "conflicts": [],
        "suggestions": [],
        "elapsed_ms": 128,
    }


def make_answer(**overrides):
    """构造一条最小可校验的 AnswerOut，可用关键字覆盖任一字段。"""
    payload = answer_payload()
    payload.update(overrides)
    return AnswerOut(**payload)


# ── 审查 I2：除 refusal_reason 外全部必填，缺字段必须报错而不是让前端 ?? [] ────────────
@pytest.mark.parametrize(
    "missing", ["answer", "citations", "conflicts", "suggestions", "elapsed_ms"]
)
def test_answer_out_fields_without_default_are_required(missing):
    payload = answer_payload()
    del payload[missing]
    with pytest.raises(ValidationError):
        AnswerOut(**payload)


def test_answer_out_required_set_matches_brief():
    required = set(AnswerOut.model_json_schema()["required"])
    assert required == {
        "refusal",
        "answer",
        "citations",
        "conflicts",
        "suggestions",
        "elapsed_ms",
    }
    assert "refusal_reason" not in required, "只有 refusal_reason 允许缺省（非拒答时就是没有原因）"


# ── 简报测试 1：拒答态必须「空答案 + 有原因」，这是「不确定就明确拒答」的契约化落点 ──
def test_refusal_with_non_empty_answer_is_rejected():
    with pytest.raises(ValidationError):
        make_answer(refusal=True, answer="编造内容", refusal_reason="not_covered")


def test_refusal_without_reason_is_rejected():
    with pytest.raises(ValidationError):
        make_answer(refusal=True, answer="", refusal_reason=None)


def test_refusal_ok_when_answer_empty_and_reason_given():
    out = make_answer(refusal=True, answer="", refusal_reason="not_covered")
    assert out.refusal is True
    assert out.refusal_reason == "not_covered"


def test_refusal_reason_is_a_closed_set():
    with pytest.raises(ValidationError):
        make_answer(refusal=True, answer="", refusal_reason="guessed")


def test_non_refusal_keeps_answer_and_no_reason():
    out = make_answer()
    assert out.refusal is False and out.refusal_reason is None


# ── 简报测试 2：出处九字段与 SourceRecord 逐一对应，防止两边漂移 ──
def test_source_out_fields_match_source_record():
    record_fields = {f.name for f in dataclasses.fields(SourceRecord)}
    own = set(SourceOut.model_fields)
    assert own == record_fields | WHITELIST_FIELDS


def test_source_out_can_be_built_from_source_record():
    """SourceRecord 直接 asdict 喂给 SourceOut 必须成立（九字段不能漂移）。"""
    record = SourceRecord(**VALID_ROW)
    out = SourceOut(**dataclasses.asdict(record))
    assert out.source_id == record.source_id
    assert out.media_type == record.media_type
    assert out.verified is False, "白名单三字段有默认值，装配时可后补"


# ── 简报测试 3：Locator 的 quote 必填、heading_path 默认空列表 ──
def test_locator_quote_is_required():
    with pytest.raises(ValidationError):
        Locator()


def test_locator_heading_path_defaults_to_empty_list():
    loc = Locator(quote="原文逐字引文")
    assert loc.heading_path == []
    assert (loc.page, loc.paragraph, loc.url_anchor) == (None, None, None)


# ── 审查 I7：定位数字必须有下界，0 与负数是「看起来有定位」的假绿 ──────────────────────
@pytest.mark.parametrize("field,value", [("page", 0), ("page", -5), ("paragraph", 0), ("paragraph", -1)])
def test_locator_positions_must_be_at_least_one(field, value):
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        Locator(**{field: value}, quote="原文逐字引文")


def test_locator_accepts_one_and_none():
    assert Locator(quote="q", page=1, paragraph=1).page == 1
    assert Locator(quote="q").page is None, "留空是合法状态（文章没有页码），但填了就必须 ≥1"


def _find_minimum(node):
    """可选整数在 openapi 里是 anyOf[integer(minimum=1), null]，递归找 minimum。"""
    if isinstance(node, dict):
        if "minimum" in node:
            return node["minimum"]
        for value in node.values():
            found = _find_minimum(value)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_minimum(item)
            if found is not None:
                return found
    return None


def test_openapi_declares_minimum_for_locator_positions():
    props = app.openapi()["components"]["schemas"]["Locator"]["properties"]
    assert _find_minimum(props["page"]) == 1
    assert _find_minimum(props["paragraph"]) == 1


# ── 白名单三字段：默认值与来源口径（装配时从 Whitelist.entries 取，不重新解析 YAML）──
def test_source_out_whitelist_fields_defaults():
    out = make_source_out()
    assert out.domain is None
    assert out.sections == []
    assert out.verified is False


def test_source_out_carries_whitelist_entry_fields():
    out = make_source_out(domain="www.dswxyjy.org.cn", sections=["/GB/427167/ 党史研究"], verified=True)
    assert out.verified is True and len(out.sections) == 1


# ── 冲突项不变式（裁决②：恰好两条 + source_id 升序）────────────────────────────────────
# 原用例只断言「刚构造出来的字面量有两条」，生产逻辑不参与，永远为绿（审查 I3 判为伪测试）。
# 现在按不变式的四个破坏面各写一条，升序通过那条同时验证顺序不被改写。
def test_conflict_item_accepts_two_sources_in_ascending_order():
    item = ConflictItem(
        subject="某地",
        predicate="事件时间",
        sides=[make_citation(1, "S002"), make_citation(2, "S005")],
    )
    assert [c.source.source_id for c in item.sides] == ["S002", "S005"], "顺序不得被改写"


def test_conflict_item_rejects_descending_source_order():
    """裁决②要求恒为升序：前端 adapter.ts 已按 sides[0]/[1] 固定排版，顺序一变就张冠李戴。"""
    with pytest.raises(ValidationError, match="升序"):
        ConflictItem(
            subject="某地",
            predicate="事件时间",
            sides=[make_citation(1, "S005"), make_citation(2, "S002")],
        )


def test_conflict_item_rejects_three_sides():
    with pytest.raises(ValidationError):
        ConflictItem(
            subject="某地",
            predicate="事件时间",
            sides=[make_citation(i, sid) for i, sid in enumerate(("S002", "S005", "S007"), start=1)],
        )


def test_conflict_item_rejects_one_side():
    with pytest.raises(ValidationError):
        ConflictItem(subject="某地", predicate="事件时间", sides=[make_citation(1, "S002")])


def test_conflict_item_rejects_two_sides_from_same_source():
    """同一来源的两个说法不是「两处记载不一致」，并列展示会误导读者。"""
    with pytest.raises(ValidationError, match="两个不同来源"):
        ConflictItem(
            subject="某地",
            predicate="事件时间",
            sides=[make_citation(1, "S002"), make_citation(2, "S002")],
        )


def test_conflict_schema_declares_exactly_two_sides():
    """JSON Schema 里要有 minItems/maxItems=2，否则前端生成的类型仍是随便长的 Citation[]。"""
    schema = ConflictItem.model_json_schema()
    sides = schema["properties"]["sides"]
    assert sides.get("minItems") == 2 and sides.get("maxItems") == 2


# ── 请求体：plan 阶段三接口约定（问题、召回条数、身份）──
def test_ask_request_defaults():
    req = AskRequest(question="某位校友在哪个历史事件中发挥了什么作用？")
    assert req.top_k == 8
    assert req.role == "学生"


def test_ask_request_role_is_a_closed_set():
    with pytest.raises(ValidationError):
        AskRequest(question="q", role="游客")


# ── 契约锁定：改名或改类型必须让这两条红（阶段零F 漂移测试的目的）──────────────────────
def test_ask_request_field_names_and_types_are_locked():
    """AskRequest 是简报外新增的模型（依据 plan 阶段三接口约定），因此更要钉死字段。"""
    fields = AskRequest.model_fields
    assert set(fields) == {"question", "top_k", "role", "source_ids", "media_types"}
    assert fields["question"].annotation is str
    assert fields["top_k"].annotation is int
    assert fields["role"].annotation == Literal["学生", "教师", "馆员"]
    assert fields["top_k"].default == 8
    assert fields["role"].default == "学生"


def test_contract_model_field_names_are_locked():
    """五个契约模型的字段名集合一次定死：前端 openapi-typescript 生成的类型全靠它们。

    阶段三按准入条件 4「可加不可改」扩展（审计字段 / verified / 来源范围），
    因此锁定集合同步扩为「阶段零F 原字段 + 阶段三新增字段」。
    """
    assert set(Locator.model_fields) == {"page", "paragraph", "heading_path", "quote", "url_anchor"}
    assert set(Citation.model_fields) == {"index", "claim", "locator", "source", "verified"}
    assert set(ConflictItem.model_fields) == {"subject", "predicate", "sides"}
    assert set(AnswerOut.model_fields) == {
        "refusal",
        "refusal_reason",
        "answer",
        "citations",
        "conflicts",
        "suggestions",
        "elapsed_ms",
        "retrieved_count",
        "top_score",
        "threshold",
        "gate_note",
    }
    assert set(AskRequest.model_fields) == {"question", "top_k", "role", "source_ids", "media_types"}


# ── 阶段三新增：可审计字段、校验标记、默认路径不变量（plan 步骤 1 / 3b / 5b）────────────
def test_citation_verified_defaults_to_false_not_true():
    """verified 默认 False：未校验的引用不得默认显示「已通过」（步骤 1 断言 c["verified"]）。"""
    assert make_citation().verified is False
    assert make_citation().model_dump()["verified"] is False


def test_answer_audit_fields_defaults():
    """审计字段有默认值（向后兼容），但拒答时必须由流水线填入真实数字（步骤 5b-2）。"""
    out = make_answer()
    assert out.retrieved_count == 0
    assert out.top_score is None
    assert out.threshold is None
    assert out.gate_note == ""


def test_refusal_reason_closed_set_includes_all_claims_rejected():
    """三种原因码：not_covered / no_evidence / all_claims_rejected（步骤 5b-2）。"""
    out = make_answer(refusal=True, answer="", refusal_reason="all_claims_rejected")
    assert out.refusal_reason == "all_claims_rejected"


def test_defaults_are_legal_constants_not_hand_waved():
    """默认路径不变量写成常量关系（步骤 3b-1），不是口头约定。"""
    assert qa_constants.DEFAULT_IDENTITY in qa_constants.IDENTITY_CHOICES
    lo, hi = qa_constants.TOP_K_RANGE
    assert lo <= qa_constants.DEFAULT_TOP_K <= hi, "默认召回数必须落在允许区间内"
    assert qa_constants.DEFAULT_TOP_K > 0
    assert qa_constants.TOP_K_RANGE[0] >= 1
    assert qa_constants.DEFAULT_MAX_DOCS > qa_constants.DEFAULT_TOP_K
    assert 0.0 < qa_constants.TERM_FLOOR < qa_constants.DEFAULT_THRESHOLD
    assert qa_constants.PROMPT_VERSION


def test_empty_source_scope_means_unrestricted_not_search_zero():
    """来源范围为空的语义必须是「不限制」（步骤 3b-1）：查 0 个来源会假装「未收录」。"""
    req = AskRequest(question="q")
    assert req.source_ids == [] and req.media_types == []
    assert qa_constants.is_unrestricted(req.source_ids, req.media_types) is True
    assert qa_constants.is_unrestricted(["S001"], []) is False


# ── 简报测试 4：契约模型必须出现在 openapi 里 ──
def test_openapi_contains_contract_models():
    schemas = app.openapi()["components"]["schemas"]
    assert {"AnswerOut", "ConflictItem", "Citation", "Locator", "SourceOut", "AskRequest"} <= set(schemas)
    assert "citations" in schemas["AnswerOut"]["properties"]
    assert "sides" in schemas["ConflictItem"]["properties"]


def test_openapi_declares_ask_and_keeps_health():
    paths = app.openapi()["paths"]
    assert "/api/ask" in paths and "post" in paths["/api/ask"]
    assert "/api/health" in paths


# ── 简报测试 5：导出脚本不起服务、不读环境变量即可产出可解析文档 ──
def test_export_openapi_writes_readable_file(tmp_path):
    from scripts.export_openapi import main

    out = tmp_path / "openapi.json"
    main(["--out", str(out)])
    spec = json.loads(out.read_text(encoding="utf-8"))
    assert "/api/ask" in spec["paths"]


def test_export_openapi_writes_utf8_without_escaping(tmp_path):
    from scripts.export_openapi import main

    out = tmp_path / "o.json"
    main(["--out", str(out)])
    text = out.read_text(encoding="utf-8")
    assert "\\u" not in text, "中文不得转义成 \\uXXXX"
    assert text.endswith("\n"), "生成物要有尾换行"
