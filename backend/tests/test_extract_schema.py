"""抽取结构与规则兜底（阶段一步骤 6–7）的测试。

plan 的原话是「引文必须能在原文逐字定位」——这是全局约束 2（答案必须有出处）的地基，
所以这里既测「什么算合格条目」，也测「不合格的条目必须被丢掉而不是被留着」。
"""

import copy
import csv
import dataclasses
import json
from pathlib import Path

import pytest
from helpers import row

from app.ingestion.extract import (
    VALID_CARD_TYPES,
    VALID_PREDICATES,
    CardDraft,
    ClaimDraft,
    LlmExtractor,
    StubExtractor,
    extract_cards,
    match_quote,
)
from app.ingestion.parse import parse_document
from app.ingestion.registry import SourceRecord

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STUB_FILE = FIXTURES / "抽取桩件结果.json"

# 与 示例文章.html 正文逐字对得上的引文（改动 fixture 必须同步改桩件，否则测试红）
QUOTE_CREATE = "讲习所于一九二五年创设，学员多为产业工人。"
QUOTE_LIBERATE = "第二段正文，一九四九年四月本地解放。"


def fixture_source(source_id="S001"):
    return SourceRecord(**row(source_id=source_id, media_type="文章"))


def fixture_doc(source_id="S001"):
    return parse_document(fixture_source(source_id), FIXTURES / "示例文章.html")


def good_claim(**over):
    claim = {
        "subject": "讲习所",
        "predicate": "事件时间",
        "value": "一九二五年",
        "quote": QUOTE_CREATE,
        "locator": {"paragraph": 2, "heading_path": ["示例文章标题", "第一节 创设"], "quote": QUOTE_CREATE},
        "confidence": 0.9,
    }
    claim.update(over)
    return claim


def payload_for(claims, card_type="event", name="讲习所创设"):
    return {"S001": [{"type": card_type, "name": name, "summary": "演示卡片", "claims": claims}]}


def claims_of(cards):
    return [cl for c in cards for cl in c.claims]


# ── plan 阶段一步骤 6 的原文用例（逐字保留）────────────────────────────────────────────
def test_extract_returns_valid_card_schema():
    cards = extract_cards(fixture_doc(), fixture_source(), StubExtractor(STUB_FILE))
    assert cards and all(c.type in {"person", "event", "place", "time", "relation"} for c in cards)
    for c in cards:
        assert c.claims, f"{c.name} 无事实条目"
        for cl in c.claims:
            assert cl.quote and cl.quote in fixture_doc().full_text, "引文必须能在原文逐字定位"


# ── 受控表本身 ────────────────────────────────────────────────────────────────────────
def test_valid_card_types_match_plan():
    assert VALID_CARD_TYPES == {"person", "event", "place", "time", "relation"}


def test_valid_predicates_match_controlled_table():
    assert VALID_PREDICATES == {
        "生卒年",
        "籍贯",
        "职务",
        "参与事件",
        "事件时间",
        "事件地点",
        "事件结果",
        "人物关系",
    }


def test_draft_dataclass_fields_are_locked():
    assert {f.name for f in dataclasses.fields(ClaimDraft)} == {
        "subject",
        "predicate",
        "value",
        "quote",
        "locator",
        "confidence",
        "hit_kind",
    }
    assert {f.name for f in dataclasses.fields(CardDraft)} == {"type", "name", "summary", "claims"}


# ── 规则兜底：不合格条目一律丢弃（表外即丢弃该条）──────────────────────────────────────
def test_predicate_outside_controlled_table_is_dropped():
    doc, source = fixture_doc(), fixture_source()
    cards = extract_cards(
        doc,
        source,
        StubExtractor(payload_for([good_claim(), good_claim(predicate="爱好", value="读书")])),
    )
    predicates = [cl.predicate for cl in claims_of(cards)]
    assert predicates == ["事件时间"], "表外谓词必须被丢弃，合格条目不受牵连"


def test_empty_quote_is_dropped():
    doc, source = fixture_doc(), fixture_source()
    cards = extract_cards(doc, source, StubExtractor(payload_for([good_claim(quote="")])))
    assert cards == []


def test_quote_not_locatable_in_source_text_is_dropped():
    """逐字定位是约束 2 的地基：原文里找不到引文的条目必须丢，哪怕看起来很合理。"""
    doc, source = fixture_doc(), fixture_source()
    cards = extract_cards(
        doc, source, StubExtractor(payload_for([good_claim(quote="讲习所于一九二五年秋创设于长沙。")]))
    )
    assert cards == []


def test_forged_stub_entries_cannot_pass_the_safety_net():
    """桩件自身造假也必须被兜底清空。

    为什么单独立一条：plan 步骤 6 那段只扫「活下来的卡片」，我用变异实验实测过——把逐字定位
    那两行删掉后，plan 那段照样 PASSED（真桩件的引文本就合法，扫它扫不出问题）。
    所以这条显式喂一份「句子通顺但原文里没有」的桩件，让那两行检查有真实回归捕获力。
    """
    forged = copy.deepcopy(json.loads(STUB_FILE.read_text(encoding="utf-8-sig")))
    for card in forged["S001"]:
        for claim in card["claims"]:
            claim["quote"] = "据可靠消息，讲习所于一九二八年秋在长沙创设。"
            claim["locator"]["quote"] = claim["quote"]
    doc, source = fixture_doc(), fixture_source()
    assert extract_cards(doc, source, StubExtractor(forged)) == []


@pytest.mark.parametrize("confidence", [-0.1, 1.5, 1.01, -1])
def test_confidence_out_of_unit_interval_is_dropped(confidence):
    doc, source = fixture_doc(), fixture_source()
    cards = extract_cards(doc, source, StubExtractor(payload_for([good_claim(confidence=confidence)])))
    assert claims_of(cards) == []


def test_confidence_boundaries_are_accepted():
    doc, source = fixture_doc(), fixture_source()
    cards = extract_cards(
        doc, source, StubExtractor(payload_for([good_claim(confidence=0.0), good_claim(confidence=1.0)]))
    )
    assert len(claims_of(cards)) == 2


def test_card_type_outside_five_values_is_dropped():
    doc, source = fixture_doc(), fixture_source()
    cards = extract_cards(doc, source, StubExtractor(payload_for([good_claim()], card_type="organization")))
    assert cards == []


def test_card_whose_claims_all_dropped_is_dropped():
    doc, source = fixture_doc(), fixture_source()
    cards = extract_cards(
        doc, source, StubExtractor(payload_for([good_claim(predicate="生平"), good_claim(quote="")]))
    )
    assert cards == [], "所有条目都不合格的卡片不得留下空卡"


def test_missing_locator_is_dropped():
    doc, source = fixture_doc(), fixture_source()
    claim = good_claim()
    del claim["locator"]
    cards = extract_cards(doc, source, StubExtractor(payload_for([claim])))
    assert claims_of(cards) == []


def test_card_missing_required_field_is_dropped():
    doc, source = fixture_doc(), fixture_source()
    bad = {"type": "event", "name": "", "summary": "s", "claims": [good_claim()]}
    cards = extract_cards(doc, source, StubExtractor({"S001": [bad]}))
    assert cards == []


# ── 注入契约：Extractor 只是协议，测试可换任何实现 ─────────────────────────────────────
def test_extractor_is_injectable():
    class Hand:
        def __init__(self):
            self.calls = 0

        def extract(self, doc, source):
            self.calls += 1
            return payload_for([good_claim()])["S001"]

    hand = Hand()
    cards = extract_cards(fixture_doc(), fixture_source(), hand)
    assert len(cards) == 1 and hand.calls == 1


def test_stub_extractor_returns_copies_not_internal_state():
    stub = StubExtractor(STUB_FILE)
    first = stub.extract(fixture_doc(), fixture_source())
    first[0]["claims"].clear()
    assert stub.extract(fixture_doc(), fixture_source())[0]["claims"], "桩件不得被调用方改坏内部数据"


def test_stub_extractor_without_entry_for_source_returns_empty(tmp_path):
    stub = StubExtractor({"S002": []})
    assert stub.extract(fixture_doc(), fixture_source("S001")) == []


# ── 重试两次后转人工补录 ──────────────────────────────────────────────────────────────
class Failing:
    """每次都抛异常的抽取后端，用来验证重试次数与人工补录。"""

    def __init__(self, message="模型超时"):
        self.message = message
        self.calls = 0

    def extract(self, doc, source):
        self.calls += 1
        raise RuntimeError(self.message)


def read_backlog(path):
    """按标准 CSV 方式读回（不要用 splitlines：字段里一旦有换行就会把行拆坏）。"""
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def test_retry_twice_then_manual_backfill(tmp_path):
    """plan 步骤 7：抽取失败重试两次后转人工补录，落盘要能看出是哪个来源、为什么、原文是什么。"""
    failing = Failing()
    cards = extract_cards(fixture_doc(), fixture_source(), failing, backlog_path=tmp_path / "待人工补录.csv")
    assert cards == []
    assert failing.calls == 3, f"应当「首次 + 重试两次」共三次，实际 {failing.calls}"
    rows = read_backlog(tmp_path / "待人工补录.csv")
    assert len(rows) == 1
    assert rows[0]["source_id"] == "S001"
    assert "模型超时" in rows[0]["reason"]
    excerpt = rows[0]["excerpt"]
    assert excerpt and " ".join(fixture_doc().full_text.split()).startswith(excerpt[:20])
    assert "\n" not in excerpt, "补录表每行必须是单行，否则按行统计的脚本会被字段内换行拆坏"


def test_empty_extraction_also_goes_to_backlog(tmp_path):
    backlog = tmp_path / "待人工补录.csv"
    cards = extract_cards(fixture_doc(), fixture_source(), StubExtractor({}), backlog_path=backlog)
    assert cards == []
    text = backlog.read_text(encoding="utf-8")
    assert "S001" in text and "未抽到" in text


def test_all_claims_dropped_counts_as_needing_manual_review(tmp_path):
    """条目全被兜底丢掉，等于该来源没产出可用事实，同样要进人工补录，不能静默 0 卡。"""
    backlog = tmp_path / "待人工补录.csv"
    doc, source = fixture_doc(), fixture_source()
    cards = extract_cards(
        doc,
        source,
        StubExtractor(payload_for([good_claim(predicate="爱好")])),
        backlog_path=backlog,
    )
    assert cards == []
    assert "S001" in backlog.read_text(encoding="utf-8")


def test_successful_extraction_writes_no_backlog(tmp_path):
    backlog = tmp_path / "待人工补录.csv"
    doc, source = fixture_doc(), fixture_source()
    cards = extract_cards(doc, source, StubExtractor(STUB_FILE), backlog_path=backlog)
    assert cards
    assert not backlog.exists()


# ── LlmExtractor：本轮无 key，只测代码与错误路径，且必须不静默降级 ──────────────────────
def test_llm_extractor_reports_missing_env_vars_loudly(monkeypatch):
    for var in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "LLM_BACKEND"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(RuntimeError) as exc:
        LlmExtractor()
    msg = str(exc.value)
    assert "LLM_API_KEY" in msg and "LLM_BASE_URL" in msg and "LLM_MODEL" in msg
    assert "为空" in msg, "必须点明是配置为空，而不是笼统的「初始化失败」"
    assert ".env.example" in msg, "要给出可执行的补齐路径"


def test_llm_extractor_does_not_fallback_silently(monkeypatch):
    """缺 key 只能抛错：不许返回空卡片冒充「抽到了但没内容」。

    显式用 StubExtractor 是无 key 环境下唯一可跑通的路径，且必须由调用方主动选，
    代码不得自己换——这就是为什么这里同时断言桩件是可用的另一条路。
    """
    for var in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(RuntimeError):
        LlmExtractor()
    doc, source = fixture_doc(), fixture_source()
    assert doc.full_text  # 文档本身没问题，失败只应来自配置缺失
    assert StubExtractor(STUB_FILE).extract(doc, source), "桩件路径可用，且只有显式构造才走它"


def test_llm_prompt_is_pinned_to_verbatim_quotes(monkeypatch):
    """提示词里的硬约束是「只抽原文出现的事实 + 每条附逐字引文」，改松一句就会放开创造性补全。"""
    for var, value in (("LLM_API_KEY", "sk-test"), ("LLM_BASE_URL", "https://x/v1"), ("LLM_MODEL", "m")):
        monkeypatch.setenv(var, value)
    prompt = LlmExtractor().build_prompt(fixture_doc())
    assert "只抽原文出现的事实" in prompt
    assert "逐字引文" in prompt
    # 原文必须逐段喂进去（带段号），不能只给摘要——否则模型无从抽取逐字引文
    for block in fixture_doc().blocks:
        assert block.text in prompt
    assert "不得补全或推断" in prompt


# ── 审查 I3：引文匹配的口径与命中块归属 ──────────────────────────────────────────────
def test_match_quote_strict_hit_carries_block():
    kind, block = match_quote(QUOTE_CREATE, fixture_doc())
    assert kind == "strict"
    assert block.text == QUOTE_CREATE


def test_match_quote_normalized_hit_is_labelled_not_dropped():
    """只差一个空格/全半角时算「归一后命中」，要标记而不是当假引文丢掉（决策记录 002 D02-8）。"""
    kind, block = match_quote("讲习所于一九二五年创设， 学员多为产业工人。", fixture_doc())
    assert kind == "normalized"
    assert block.text == QUOTE_CREATE


def test_match_quote_spliced_across_blocks_is_not_a_hit():
    """跨块拼接的句子在 full_text 里能命中，但不属于任何一块——必须判为不命中。

    否则一条「前一段结尾 + 后一段开头」拼出来的假引文能过逐字闸门，阶段七按 locator
    回跳时又会指到不相干的段落，属于「看起来可定位」的假绿。
    """
    doc = fixture_doc()
    spliced = "学员多为产业工人。 第二段正文"
    assert spliced.replace(" ", "") in doc.full_text.replace("\n", "").replace(" ", "")
    assert match_quote(spliced, doc)[0] is None


def test_match_quote_absent_returns_none():
    assert match_quote("这句话原文里根本没有。", fixture_doc()) == (None, None)


def test_quote_and_locator_must_point_at_the_same_block():
    """条目 quote 与 locator 指向的块不一致时丢弃：审核台按 locator 回跳会指错地方。"""
    doc, source = fixture_doc(), fixture_source()
    wrong = good_claim(
        quote=QUOTE_LIBERATE,
        locator={
            "paragraph": 2,
            "heading_path": ["示例文章标题", "第一节 创设"],
            "quote": QUOTE_CREATE,
            "url_anchor": "p-2",
        },
    )
    assert extract_cards(doc, source, StubExtractor(payload_for([wrong]))) == []


def test_locator_position_must_match_the_hit_block():
    """引文命中第 3 段，locator 却写第 1 段 → 丢弃。"""
    doc, source = fixture_doc(), fixture_source()
    bad = good_claim(
        quote=QUOTE_LIBERATE,
        locator={
            "paragraph": 1,
            "heading_path": ["示例文章标题", "第一节 创设"],
            "quote": QUOTE_LIBERATE,
            "url_anchor": "p-1",
        },
    )
    assert extract_cards(doc, source, StubExtractor(payload_for([bad]))) == []


# ── 审查 I4：value 必须在自己的引文里找得到依据（约束 5 的落地）───────────────────────
def test_value_not_supported_by_its_quote_is_dropped():
    """桩件自己就是违规例证：value「为讲习所学员」在原文措辞「学员多为产业工人」里找不到。"""
    doc, source = fixture_doc(), fixture_source()
    assert extract_cards(
        doc, source, StubExtractor(payload_for([good_claim(value="为讲习所学员")]))
    ) == []


@pytest.mark.parametrize("value", ["一九二五年", "产业工人", "学员多为产业工人"])
def test_value_taken_from_the_quote_is_kept(value):
    doc, source = fixture_doc(), fixture_source()
    cards = extract_cards(doc, source, StubExtractor(payload_for([good_claim(value=value)])))
    assert [cl.value for cl in claims_of(cards)] == [value]


def test_value_may_differ_only_by_width_and_spacing():
    """取值与引文只差全半角/空格时仍算有依据，别把排版差异当创造性补充。"""
    doc, source = fixture_doc(), fixture_source()
    cards = extract_cards(
        doc, source, StubExtractor(payload_for([good_claim(value="讲习所于一九二五年创设")]))
    )
    assert claims_of(cards)[0].value == "讲习所于一九二五年创设"


def test_shipped_stub_has_no_value_without_evidence():
    """仓库里那份桩件必须过自己的判据——它曾经违规，说明造桩件时没跑校验。"""
    doc = fixture_doc()
    cards = extract_cards(doc, fixture_source(), StubExtractor(STUB_FILE))
    assert cards, "桩件在收紧判据后仍应有产出，否则说明判据过严"
    for card in cards:
        for claim in card.claims:
            assert claim.value.replace(" ", "") in claim.quote.replace(" ", "")
