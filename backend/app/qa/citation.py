"""阶段三 T3-3：三层引用校验（plan 步骤 4：编号 / 逐字 / 主体一致）。

防的是「张冠李戴」：答案语气专业、格式完整、句末带 [n]，但 [n] 指向的证据根本没说这件事。
三层任一层不过就剔除该句；全部剔除时由流水线转 `all_claims_rejected` 拒答（步骤 5b-2）。
校验结果同时供 `audit_logs` 落盘（plan 接口约定的 VerifiedAnswer）。

归一口径只有一份：`retrieval.textmatch.normalize_title/normalize_text`（规范 6.9）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from app.qa.evidence import Evidence
from app.qa.schemas import Citation
from app.retrieval.textmatch import contains_fact, normalize_title

_SENTENCE_SPLIT = re.compile(r"(?<=[。！？])")
_REF = re.compile(r"\[(\d+)\]")


class Verdict(str, Enum):
    """一句的校验裁定（写入 audit_logs.verdict 的 kept/dropped 与 reason）。"""

    KEPT = "kept"
    NO_CITATION = "no_citation"
    BAD_INDEX = "bad_index"
    QUOTE_NOT_FOUND = "quote_not_found"
    SUBJECT_MISMATCH = "subject_mismatch"


@dataclass(frozen=True)
class SentenceVerdict:
    sentence: str
    verdict: Verdict
    reason: str
    citation_indexes: list[int] = field(default_factory=list)
    citation: Citation | None = None


@dataclass(frozen=True)
class VerifiedAnswer:
    kept: list[SentenceVerdict]
    dropped: list[SentenceVerdict]

    @property
    def all_rejected(self) -> bool:
        return bool(self.dropped) and not self.kept

    @property
    def answer_text(self) -> str:
        return "".join(item.sentence for item in self.kept)


def _norm_subject(text: str, aliases: dict[str, list[str]]) -> str:
    """主体归一：NFKC + 别名展开 + 只留字母数字汉字（复用标题归一，规范 6.9）。"""
    canonical = text
    for alias, names in aliases.items():
        if normalize_title(text) == normalize_title(alias) or normalize_title(text) in {
            normalize_title(n) for n in names
        }:
            canonical = alias
            break
    return normalize_title(canonical)


def _make_citation(index: int, e: Evidence) -> Citation:
    """由证据组装出一条 Citation（verified 由调用方在通过校验后置 True）。"""
    return Citation(
        index=index,
        claim=e.subject if not e.predicate else f"{e.subject}·{e.predicate}：{e.value}",
        locator=e.locator,
        source=e.source,
        verified=True,
    )


def verify_answer(
    draft: str,
    evidence: list[Evidence],
    *,
    source_texts: dict[int, str] | None = None,
    aliases: dict[str, list[str]] | None = None,
    alias_path: str | Path | None = None,
) -> VerifiedAnswer:
    """逐句校验草稿答案，返回保留与剔除的裁定。

    `source_texts`（可选）：claim_id → 解析原文全文，用于第二层「引文逐字定位」；
    `None` 表示引文来自条目表本身、以其自证；显式传空 dict 表示「无原文可核」，按未通过处理（4.12）。
    `aliases` / `alias_path`：第三层主体一致用的别名表（形如 `{"省立一师": ["省立第一师范学校"]}`）。
    """
    by_index = {i + 1: e for i, e in enumerate(evidence)}
    alias_map = dict(aliases or {})
    if alias_path is not None:
        import yaml

        loaded = yaml.safe_load(Path(alias_path).read_text(encoding="utf-8")) or {}
        for key, value in loaded.items():
            alias_map.setdefault(str(key), list(value or []))

    kept: list[SentenceVerdict] = []
    dropped: list[SentenceVerdict] = []
    for raw in _SENTENCE_SPLIT.split(draft):
        sentence = raw.strip()
        if not sentence:
            continue
        refs = [int(x) for x in _REF.findall(sentence)]
        if not refs:
            dropped.append(SentenceVerdict(sentence, Verdict.NO_CITATION, "结论句没有引用编号"))
            continue
        if any(r not in by_index for r in refs):
            bad = [r for r in refs if r not in by_index]
            dropped.append(SentenceVerdict(sentence, Verdict.BAD_INDEX, f"引用编号不存在于本次证据集：{bad}"))
            continue
        # 第二层 + 第三层：每个被引用的证据都要过，任一不过即剔除整句。
        failure: Verdict | None = None
        reason = ""
        for r in refs:
            e = by_index[r]
            if source_texts is not None:
                original = source_texts.get(r)
                if not original or not contains_fact(original, e.quote):
                    failure, reason = Verdict.QUOTE_NOT_FOUND, f"[{r}] 引文未能在解析原文中逐字定位"
                    break
            subject_norm = _norm_subject(e.subject, alias_map)
            if not subject_norm or subject_norm not in _norm_subject(sentence, alias_map):
                failure, reason = Verdict.SUBJECT_MISMATCH, f"[{r}] 答案主语与条目主体不一致"
                break
        if failure is not None:
            dropped.append(SentenceVerdict(sentence, failure, reason))
            continue
        citation = _make_citation(refs[0], by_index[refs[0]])
        kept.append(SentenceVerdict(sentence, Verdict.KEPT, "三层校验通过", refs, citation))
    return VerifiedAnswer(kept=kept, dropped=dropped)
