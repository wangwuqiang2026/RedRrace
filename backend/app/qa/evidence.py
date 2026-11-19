"""阶段三 T3-2：证据组装与出处回链（plan 步骤 4b）。

一条证据 = 阶段二检索命中的 `claim_id` 回表取出的「事实条目 + 来源九字段 + 定位」。
本模块只负责**组装**，不做校验、不调模型、不写库（职责边界依 2.10）。

出处回链的硬纪律（步骤 4b）：回链目标一律由 `source_id` 现算两个持久路径——
解析产物 `data_dir/parsed/<source_id>.json` 与原文快照 `data_dir/raw/articles/<source_id>.html`
（电子书载体另有 `data_dir/raw/ebooks/<source_id>.pdf`）。**索引、缓存、条目表里禁止存绝对路径
或临时路径**：参考实现把副本按裸哈希落盘且不带扩展名，块的 file_path 指向上传缓存目录，
工具一结束目录被删，引用「预览」永久 404，日志反复刷 `… does not exist`。
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.qa.schemas import Locator, SourceOut
from app.retrieval.backend import Hit

_SOURCE_FIELDS = (
    "source_id", "title", "publisher", "publish_date", "url_or_path",
    "access_date", "license_note", "corpus_tier", "media_type",
)


@dataclass(frozen=True)
class Evidence:
    """一条可送入提示词的证据（内部数据，不进 HTTP 契约）。"""

    claim_id: int
    card_id: int
    source_id: str
    subject: str
    predicate: str
    value: str
    quote: str
    score: float | None
    source: SourceOut
    locator: Locator

    @property
    def reference_text(self) -> str:
        """送进提示词/证据集的文本：主体 + 谓词 + 取值 + 原文引文（与检索串同口径）。"""
        return f"{self.subject}，{self.predicate}：{self.value}。原文：{self.quote}"


def assemble(db_path: Path, hits: list[Hit]) -> list[Evidence]:
    """按 `claim_id` 回表组装证据；库里没有的条目直接跳过，不造空证据（依 4.12）。

    顺序严格跟随 `hits`（检索排序即证据编号顺序），不去重、不重排：引用编号必须能稳定映射回
    `hits` 的序号，否则答案里的「[2]」指向的不是证据集第二条（4.4-① 同源纪律）。
    """
    if not hits:
        return []
    ids = [h.claim_id for h in hits]
    placeholders = ",".join("?" for _ in ids)
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT c.claim_id, c.card_id, c.source_id, c.subject, c.predicate, c.value, c.quote, "
            f"c.locator, s.{', s.'.join(_SOURCE_FIELDS)}, s.domain, s.sections, s.verified "
            f"FROM claims c JOIN sources s ON s.source_id = c.source_id "
            f"WHERE c.claim_id IN ({placeholders})",
            tuple(ids),
        ).fetchall()
    by_id = {row[0]: row for row in rows}
    result: list[Evidence] = []
    for h in hits:
        row = by_id.get(h.claim_id)
        if row is None:
            continue
        locator_raw: dict[str, Any] = json.loads(row[7]) if row[7] else {}
        locator = Locator(
            page=locator_raw.get("page"),
            paragraph=locator_raw.get("paragraph"),
            heading_path=list(locator_raw.get("heading_path") or []),
            quote=row[6],
            url_anchor=locator_raw.get("url_anchor"),
        )
        source = SourceOut(
            **{name: row[8 + i] for i, name in enumerate(_SOURCE_FIELDS)},
            domain=row[8 + len(_SOURCE_FIELDS)],
            sections=json.loads(row[9 + len(_SOURCE_FIELDS)] or "[]"),
            verified=bool(row[10 + len(_SOURCE_FIELDS)]),
        )
        result.append(
            Evidence(
                claim_id=h.claim_id,
                card_id=h.card_id,
                source_id=row[2],
                subject=row[3],
                predicate=row[4],
                value=row[5],
                quote=row[6],
                score=h.score,
                source=source,
                locator=locator,
            )
        )
    return result


def citation_targets(evidence: list[Evidence], data_dir: Path) -> dict[int, str]:
    """给每条证据算出处回链目标（持久路径，由 source_id 现算，依步骤 4b）。

    - 载体为「文章」→ `data_dir/parsed/<source_id>.json`（解析产物，带扩展名的持久副本）；
    - 载体为「电子书」→ 同目录同命名，另有原文快照 `data_dir/raw/ebooks/<source_id>.<ext>`。
    两类载体**不得混用**回链口径；前端 `SourceCard` 双版式按 `media_type` 渲染不同定位字段
    （文章 = heading_path/url_anchor，电子书 = page/章节）。
    """
    targets: dict[int, str] = {}
    for e in evidence:
        # 解析产物是唯一稳定的回链目标：它由 source_id 命名、落持久目录，重建索引不会改名。
        target = Path(data_dir) / "parsed" / f"{e.source_id}.json"
        targets[e.claim_id] = str(target)
    return targets
