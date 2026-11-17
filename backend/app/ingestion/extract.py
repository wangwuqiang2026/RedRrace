"""抽取、结构校验与规则兜底（阶段一步骤 6–7）。

流程固定为三段：**抽取（可注入后端）→ 结构校验 → 规则兜底丢弃**。

三条不可让的口径（plan 全局约束 2／5 与决策记录 002）：

1. **逐字引文**：条目的 `quote` 必须能在该来源的 `ParsedDoc.full_text` 里原样命中，命不中就丢弃。
   本轮是严格的子串比对；阶段三的引用校验才会引入全半角/空白归一后的宽松定位（决策记录 002 第 8 条），
   两者不要混为一谈。
2. **受控谓词表**：表外谓词直接丢弃该条，不做近义归并——猜错谓词会造出假冲突。
3. **不猜**：抽取失败或全部条目不合格时，重试两次后转人工补录（`data/待人工补录.csv`），
   绝不留下空卡片，也不静默产出 0 条。
"""

from __future__ import annotations

import copy
import csv
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic import ValidationError

from app.core.config import get_config
from app.ingestion.parse import Block, ParsedDoc
from app.ingestion.registry import SourceRecord
from app.qa.schemas import Locator

# plan 阶段一步骤 6 的测试逐字用到这五个值
VALID_CARD_TYPES = {"person", "event", "place", "time", "relation"}
# 决策记录 002 第 9 条的受控谓词表：表外即丢弃该条
VALID_PREDICATES = {
    "生卒年",
    "籍贯",
    "职务",
    "参与事件",
    "事件时间",
    "事件地点",
    "事件结果",
    "人物关系",
}

# 首次 + 重试两次（plan 步骤 7「抽取失败重试两次后转人工补录」）
MAX_ATTEMPTS = 3

# 在线抽取单次请求超时（秒）。原先是调用点上的裸数字 `timeout=120`，落在 T0 实测的两个数之间：
# 漏发 `enable_thinking=false` 时单次 140.5s、发了 9.8s（决策记录 007 第五节 A/B；T0 报告 §2.3）。
# 120s 于是把「配置项没接线」伪装成「网络偶发超时」——再乘 MAX_ATTEMPTS 就是每单元最多 6 分钟
# 纯等待，并把 ReadTimeout 刷进人工补录表，掩盖真实故障。取 300s 的依据：长文档 S020 实测
# 63–67s 需要余量，而真慢（推理未关）应表现为「慢得离谱」而非「刚好超时」。
# 未做成 Config 字段的原因见 task15-report.md：新增配置项须先经 lead 裁决并同步 `.env.example`
# （规范 7.10 第④条、裁决 D11 的单点归属），本任务写范围不含 `core/config.py`。
LLM_TIMEOUT_S = 300

# 人工补录表的三列
BACKLOG_COLUMNS = ("source_id", "reason", "excerpt")

# 归一比对要抹掉的差异：空白 + 中英文标点。全半角由 NFKC 负责，但 NFKC 不折叠中文句号
# 「。」与书名号（与 registry.normalize_org 遇到的同一件事），所以这里显式列出。
_QUOTE_NOISE_RE = re.compile(
    r"[\s，。、；：！？“”‘’'\"（）()《》〈〉【】\[\]．.…—–―~～-]+"
)


def _default_backlog_path() -> Path:
    """补录表默认落点：跟着 `Config.data_dir` 走。

    曾经这里是硬编码的 `backend/data/待人工补录.csv`，于是每一次全量 pytest 都往仓库里
    追加 11 行 fixture 噪声，把真实待办埋掉（审查 C2）。改成走配置后，测试会话只需把
    `DATA_DIR` 指到临时目录（`conftest.py` 的 autouse fixture 负责），生产 CLI 默认仍落在
    数据目录里，两边都不用传参也不会写脏仓库。
    """
    return get_config().data_dir / "待人工补录.csv"

# 提示词硬约束：只许抽原文出现的事实，每条附逐字引文，不给创造性补全留余地
PROMPT_TEMPLATE = """你是党史语料结构化助手。只处理下面这篇原文，不得引入任何外部知识。

要求：
1. 只抽原文出现的事实，原文没有写的（生卒年、职务、时间、地点、关系）一律不得补全或推断；
2. 每条事实必须附**逐字引文**，引文必须能在原文中原样找到；
3. 每条事实归入受控谓词之一：{predicates}；
4. 每张卡片归入类型之一：{types}；
5. 每条给出 0 到 1 之间的置信度；找不到依据就不要输出该条，宁缺毋滥；
6. 只输出 JSON，形如 {{"cards": [{{"type": "...", "name": "...", "summary": "...",
   "claims": [{{"subject": "...", "predicate": "...", "value": "...", "quote": "...",
   "paragraph": 1, "confidence": 0.9}}]}}]}}，不要输出解释文字。

原文（每段前有段号）：
{text}
"""


@dataclass
class ClaimDraft:
    """事实条目草稿。

    `hit_kind` 记录引文是怎么落回原文的：`strict` 逐字命中、`normalized` 归一后命中
    （全半角/空白/标点差异）。它是给人看的可信度信号——阶段七审核台要能一眼挑出归一命中
    那批复核；入库文本仍保存逐字原样，归一只用于判定。
    """

    subject: str
    predicate: str
    value: str
    quote: str
    locator: Locator
    confidence: float
    hit_kind: str = "strict"


@dataclass
class CardDraft:
    """卡片草稿：一张卡至少一条事实条目，空卡不得存在。"""

    type: str
    name: str
    summary: str
    claims: list[ClaimDraft] = field(default_factory=list)


@runtime_checkable
class Extractor(Protocol):
    """抽取后端协议：返回**原始卡片字典列表**，结构校验统一由 extract_cards 负责。"""

    def extract(self, doc: ParsedDoc, source: SourceRecord) -> list[dict[str, Any]]: ...


class StubExtractor:
    """固定桩件：按 source_id 返回预先给定的理想结果，供无 key 环境跑通链路与测试使用。

    桩件里的每条引文都必须与该来源解析出的原文逐字对得上——`extract_cards` 的兜底会当场把
    对不上的条目丢掉，所以桩件本身造假是藏不住的。
    """

    def __init__(self, payload: Any = None):
        if payload is None:
            data: dict[str, Any] = {}
        elif isinstance(payload, dict):
            data = payload
        else:
            path = Path(payload)
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        self._data = data
        self.calls: list[str] = []

    def extract(self, doc: ParsedDoc, source: SourceRecord) -> list[dict[str, Any]]:
        self.calls.append(doc.source_id)
        cards = self._data.get(doc.source_id) or []
        return copy.deepcopy(cards)


def _cards_from_response(content: str) -> list[dict[str, Any]]:
    """把模型回复正文解析成卡片列表，兼容**顶层就是数组**的形态。

    提示词要求的是 `{"cards": [...]}`，但 T0 实测 12 次调用里有 1 次（S020）返回顶层数组，
    旧写法 `json.loads(content).get("cards")` 当场抛 `AttributeError: 'list' object has no
    attribute 'get'` → `_extract_with_retries` 捕获后重试，等于白烧一次付费调用（第二次才拿到
    合法对象）。两种形态在语义上等价，所以在此归一；畸形形态（字符串、数字、缺 cards）一律
    照旧抛错走重试与人工补录——**不得**为了让解析通过而放宽引文/谓词兜底（禁止清单 8.13、8.10）。
    """
    parsed = json.loads(content)
    if isinstance(parsed, list):
        return parsed
    return parsed.get("cards", [])


class LlmExtractor:
    """在线大模型抽取后端。

    本轮**没有可用 key**：构造时缺任何一项配置就直接抛错，并点名缺哪个环境变量，
    绝不悄悄改用桩件、也不返回空卡片冒充「抽到了但没内容」。
    """

    REQUIRED_ENV = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")

    def __init__(self, config=None):
        cfg = config if config is not None else get_config()
        missing = [
            name
            for name, value in (
                ("LLM_API_KEY", cfg.llm_api_key),
                ("LLM_BASE_URL", cfg.llm_base_url),
                ("LLM_MODEL", cfg.llm_model),
            )
            if not value
        ]
        if missing:
            raise RuntimeError(
                "LlmExtractor 需要在线大模型配置，以下环境变量为空：" + "、".join(missing) + "。"
                "请复制 backend/.env.example 为 backend/.env 并填入这三项"
                "（无 key 环境下请显式改用 StubExtractor，抽取后端不会自动切换）。"
            )
        self.cfg = cfg

    def build_prompt(self, doc: ParsedDoc) -> str:
        numbered = "\n".join(f"[{b.locator.paragraph or b.locator.page or 0}] {b.text}" for b in doc.blocks)
        return PROMPT_TEMPLATE.format(
            predicates="、".join(sorted(VALID_PREDICATES)),
            types="、".join(sorted(VALID_CARD_TYPES)),
            text=numbered,
        )

    def extract(self, doc: ParsedDoc, source: SourceRecord) -> list[dict[str, Any]]:
        """调用在线接口并返回原始卡片字典。

        本方法**已被真实验证**（T1.5，2026-11-16：S001/S017/S013/S005 四个单元实跑，见
        `task15-report.md` 第五节）。原先这句写的是「本轮无 key，此路径未被真实验证」——
        那是阶段一交付时的状态；按规范 3.6，口径变更时在此注明日期与原因，不留过期表述。
        """
        import httpx

        response = httpx.post(
            f"{self.cfg.llm_base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {self.cfg.llm_api_key}"},
            json={
                "model": self.cfg.llm_model,
                "temperature": 0,
                # 混合思考开关必须**显式发送**，包括值为 False 的情况：该供应商在参数缺省时默认
                # 开启推理 token，实测单次 140.5s（reasoning 占 completion 的 89%）vs 关闭后
                # 9.8s，JSON 合规性不降（决策记录 007 第五节）。`config.py` 早就有
                # `llm_enable_thinking` 但请求体从不带它——「配置写了、行为没生效」正是规范 4.13
                # 要防的形态，也是试点入库只能靠运行期注入参数跑通、数字无法复现的根因。
                # ⚠️ 换供应商须逐项确认该扩展参数是否支持（OpenAI 官方 schema 无此项），
                #    已登记为阶段八运行手册必查项（007 第五节附注②）。
                "enable_thinking": bool(self.cfg.llm_enable_thinking),
                "messages": [
                    {"role": "system", "content": "只输出 JSON，不得输出解释。"},
                    {"role": "user", "content": self.build_prompt(doc)},
                ],
            },
            timeout=LLM_TIMEOUT_S,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return self._attach_paragraphs(_cards_from_response(content), doc)

    @staticmethod
    def _attach_paragraphs(cards: list[dict[str, Any]], doc: ParsedDoc) -> list[dict[str, Any]]:
        """把模型给的段号换成完整 Locator（含标题路径与锚点），不信任模型自报的定位文字。"""
        by_paragraph = {
            block.locator.paragraph: block.locator for block in doc.blocks if block.locator.paragraph
        }
        out = copy.deepcopy(cards)
        for card in out:
            for claim in card.get("claims", []):
                paragraph = claim.pop("paragraph", None)
                locator = by_paragraph.get(paragraph)
                claim["locator"] = (
                    {
                        "paragraph": paragraph,
                        "heading_path": list(locator.heading_path) if locator else [],
                        "quote": claim.get("quote", ""),
                        "url_anchor": locator.url_anchor if locator else None,
                    }
                    if locator
                    else None
                )
        return out


def _quote_key(text: str) -> str:
    """引文比对键：NFKC 统一全半角 + 去空白与标点。

    这是决策记录 002 D02-8 里「归一化后子串命中」那一档的实现；归一**只用于判定**，
    入库仍保存逐字原文，绝不把归一结果写回 `quote`。
    """
    return _QUOTE_NOISE_RE.sub("", unicodedata.normalize("NFKC", text or ""))


def match_quote(quote: str, doc: ParsedDoc) -> tuple[str | None, Block | None]:
    """两段式引文匹配：先严格子串，再归一子串；**只在单个块内**匹配。

    刻意不把 `full_text` 当比对底本：`full_text` 用换行拼接块，跨块拼出来的句子
    （前一段结尾 + 后一段开头）能在里面命中，却不属于任何一块——阶段七按 locator 回跳
    就会指到不相干的段落。按块匹配同时解决了「假引文」与「错定位」两件事。

    返回 `("strict"|"normalized"|None, block|None)`，`hit_kind` 随条目落库，
    人工核对时能一眼看出哪些是逐字命中、哪些是靠归一救回来的。
    """
    target = quote or ""
    if not target.strip():
        return None, None
    for block in doc.blocks:
        if target in block.text:
            return "strict", block
    key = _quote_key(target)
    if key:
        for block in doc.blocks:
            if key in _quote_key(block.text):
                return "normalized", block
    return None, None


def _validate_claim(raw: Any, doc: ParsedDoc) -> ClaimDraft | None:
    """单条事实条目的兜底校验；不合格返回 None（调用方负责丢弃）。"""
    if not isinstance(raw, dict):
        return None
    subject = str(raw.get("subject") or "").strip()
    predicate = str(raw.get("predicate") or "").strip()
    value = str(raw.get("value") or "").strip()
    quote = str(raw.get("quote") or "")
    if not subject or not predicate or not value or not quote:
        return None
    if predicate not in VALID_PREDICATES:
        return None
    confidence = raw.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return None
    if not 0.0 <= float(confidence) <= 1.0:
        return None
    # 约束 2 的地基：引文必须落回某个具体文本块。逐字命中优先，归一命中打 hit_kind 标记，
    # 跨块拼接一律不算命中（旧的 `quote in doc.full_text` 写法会放行拼接假引文，审查 I3）。
    hit_kind, hit_block = match_quote(quote, doc)
    if hit_kind is None:
        return None
    # 约束 5：取值必须能在**自己的引文**里找到依据，否则就是借「逐字引文」偷渡改写（审查 I4）。
    if _quote_key(value) not in _quote_key(quote):
        return None
    locator_raw = raw.get("locator")
    if not isinstance(locator_raw, dict):
        return None
    try:
        locator = Locator(**locator_raw)
    except (TypeError, ValidationError):
        return None
    # locator 必须指向真正命中的那块：阶段七审核台按定位回跳，指错就等于给出错误出处。
    if _quote_key(str(locator.quote)) != _quote_key(quote):
        return None
    if locator.paragraph != hit_block.locator.paragraph or locator.page != hit_block.locator.page:
        return None
    return ClaimDraft(
        subject=subject,
        predicate=predicate,
        value=value,
        quote=quote,
        locator=locator,
        confidence=float(confidence),
        hit_kind=hit_kind,
    )


def _validate_card(raw: Any, doc: ParsedDoc) -> CardDraft | None:
    """整卡校验：类型在五值内、名称非空，且至少剩下一条合格事实条目，否则整卡丢弃。"""
    if not isinstance(raw, dict):
        return None
    card_type = str(raw.get("type") or "").strip()
    name = str(raw.get("name") or "").strip()
    summary = str(raw.get("summary") or "").strip()
    if card_type not in VALID_CARD_TYPES or not name or not summary:
        return None
    claims = [
        claim
        for claim in (_validate_claim(item, doc) for item in (raw.get("claims") or []))
        if claim is not None
    ]
    if not claims:
        return None
    return CardDraft(type=card_type, name=name, summary=summary, claims=claims)


def _excerpt(doc: ParsedDoc, limit: int = 120) -> str:
    """给人工补录留一段原文，避免补录人员还得先去翻文件。

    压平成单行：CSV 字段里带换行虽然合法，但后续任何按行 grep/统计的脚本都会被绊倒，
    而补录表正是靠人逐行翻的。原文可比性靠「空白归一后仍是原文子串」保证。
    """
    return " ".join(doc.full_text.split())[:limit]


def _append_backlog(backlog_path: Path, source_id: str, reason: str, doc: ParsedDoc) -> None:
    backlog_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not backlog_path.exists()
    with backlog_path.open("a", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=BACKLOG_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow({"source_id": source_id, "reason": reason, "excerpt": _excerpt(doc)})


def _extract_with_retries(
    doc: ParsedDoc, source: SourceRecord, extractor: Extractor
) -> tuple[list[dict[str, Any]], str | None]:
    """首次 + 重试两次。返回（原始卡片列表, 失败原因）；成功时原因为 None。"""
    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            raw = extractor.extract(doc, source)
        except Exception as exc:  # noqa: BLE001  任何后端异常都按「抽取失败」重试，不外抛
            last_error = f"{type(exc).__name__}: {exc}"
            continue
        if raw:
            return list(raw), None
        last_error = "抽取返回空结果"
    return [], f"未抽到事实条目（{MAX_ATTEMPTS} 次尝试均无产出；最后状态：{last_error}）"


def extract_cards(
    doc: ParsedDoc,
    source: SourceRecord,
    extractor: Extractor,
    *,
    backlog_path: Path | None = None,
) -> list[CardDraft]:
    """抽取 → 结构校验 → 规则兜底，返回可用卡片；不合格产出全部丢弃并转人工补录。

    `backlog_path` 可省略，省略时落 `Config.data_dir / 待人工补录.csv`；测试会话由
    `conftest.py` 的 autouse fixture 把 `DATA_DIR` 指到临时目录，所以跑套件不可能写脏仓库
    （审查 C2 的根因修复）。需要精确断言落点时（如重试次数与补录内容）就显式传 `tmp_path`。
    """
    backlog = _default_backlog_path() if backlog_path is None else Path(backlog_path)
    raw_cards, error = _extract_with_retries(doc, source, extractor)
    if error is not None:
        _append_backlog(backlog, source.source_id, error, doc)
        return []
    cards = [
        card for card in (_validate_card(raw, doc) for raw in raw_cards) if card is not None
    ]
    if not cards:
        reason = "未抽到合格事实条目：返回内容全部被规则兜底丢弃（谓词表外、引文无法逐字定位、置信度越界等）"
        _append_backlog(backlog, source.source_id, reason, doc)
    return cards
