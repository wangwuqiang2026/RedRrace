"""问答契约占位模型（阶段零F 步骤 2）：字段齐全、**无业务逻辑**。

字段名与类型一经确定不得随意改动（plan 全局约束 10「契约优先于实现」）：前端类型不手写，
由 openapi-typescript 从 `/openapi.json` 生成，后端改名即打断前端编译。
问答流水线在阶段三实现，本模块不得提前塞入任何检索或生成逻辑。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Locator(BaseModel):
    """定位信息：引用必须能点回原文。

    电子书类给 `page` 或章节标题路径，文章类给 `paragraph` + `heading_path` + `url_anchor`；
    `quote` 是原文逐字引文，必填——没有引文的出处不允许进答案。
    `page`/`paragraph` 下界为 1（审查 I7）：0 与负数一旦被接受，阶段三与阶段七的归位
    会指向「第 0 页」这种不存在的位置却毫无提示，又是一处「看起来有定位」的假绿。
    """

    page: int | None = Field(default=None, ge=1)
    paragraph: int | None = Field(default=None, ge=1)
    heading_path: list[str] = Field(default_factory=list)
    quote: str
    url_anchor: str | None = None


class SourceOut(BaseModel):
    """出处卡片数据。

    前九个字段与 `app.ingestion.registry.SourceRecord` 一一对应且**同名**（该模块改动会
    由测试 `test_source_out_fields_match_source_record` 立刻发现）；后三个白名单字段的口径
    来自 `registry.load_whitelist(...).entries`——装配时按 `normalize_org(publisher)` 取，
    任何地方都不要重新解析 YAML。
    """

    source_id: str
    title: str
    publisher: str
    publish_date: str
    url_or_path: str
    access_date: str
    license_note: str
    corpus_tier: str
    media_type: str

    domain: str | None = None
    sections: list[str] = Field(default_factory=list)
    verified: bool = False


class Citation(BaseModel):
    """一条带出处的引用：编号 + 断言 + 定位 + 来源。"""

    index: int
    claim: str
    locator: Locator
    source: SourceOut


class ConflictItem(BaseModel):
    """同一「主体 + 谓词」的两处不一致记载。

    `sides` **恰好两条、等权并列**，顺序恒按 `source_id` 升序——裁决②原本是「阶段四生成时
    保证」，但前端 `adapter.ts` 已按 `sides.length === 2` 写死排版，所以拦截点提前到契约层
    （审查 I3）：现在违反不变式的对象连构造都过不了，而不是等下游去猜。
    """

    subject: str
    predicate: str
    sides: list[Citation] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def _two_distinct_sources_in_ascending_order(self) -> ConflictItem:
        ids = [citation.source.source_id for citation in self.sides]
        if len(set(ids)) != 2:
            raise ValueError("冲突项必须是两个不同来源的记载：同一来源的两条说法不构成「两处记载不一致」")
        if ids != sorted(ids):
            raise ValueError("sides 顺序恒为 source_id 升序（裁决②），不得由调用方决定谁排前面")
        return self


class AskRequest(BaseModel):
    """提问请求：问题、召回条数、身份（plan 阶段一/三「接口约定」）。"""

    question: str
    top_k: int = 8
    role: Literal["学生", "教师", "馆员"] = "学生"


class AnswerOut(BaseModel):
    """回答结构：是否拒答、答案正文、引用列表、冲突组、参考建议、耗时。

    除 `refusal_reason` 外**全部必填**（审查 I2）：简报把它们写成无默认值字段，之前我给了
    默认值，导致 openapi 的 `required` 只剩 `refusal`，前端生成的类型变成 `citations?: Citation[]`
    并被迫到处 `?? []`——契约强比宽松好，后端漏填一个字段就该在序列化前报错，而不是让
    「忘了填」和「确实没有」在前端长得一模一样。
    """

    refusal: bool
    # 简报原写 `Literal["not_covered", "no_evidence", None]`；ruff 的 PYI061 要求把 None 挪出
    # Literal。两种写法的**取值集合相同**（两个字符串 + null），但 JSON Schema 结构不同：
    #   Literal[..., None]   -> {"enum": ["not_covered", "no_evidence", null]}
    #   Literal[...] | None  -> {"anyOf": [{"enum": [...], "type": "string"}, {"type": "null"}]}
    # 这里按 ruff 采用后者。openapi-typescript 对两种结构一般都解析成
    # `"not_covered" | "no_evidence" | null`，但这一点须由前端用真实生成结果确认
    # （已写进报告的风险项，也在给 frontend-dev 的通知里点名）；若生成结果确有差异，
    # 改回原写法并在该行加 ruff 对 PYI061 的豁免注释即可，取值集合不变。
    refusal_reason: Literal["not_covered", "no_evidence"] | None = None
    answer: str
    citations: list[Citation]
    conflicts: list[ConflictItem]
    suggestions: list[str]
    elapsed_ms: int

    @model_validator(mode="after")
    def _refusal_means_empty_answer_with_reason(self) -> AnswerOut:
        """拒答态的硬约束：答案必须是空串，且必须给出拒答原因。

        这是「查不到就明确拒答、绝不用模型知识补写」（plan 全局约束 3、5）在契约层的落点：
        一旦有人构造出「refusal=True 却带着答案文本」的响应，序列化前就会炸，而不是
        把补写内容悄悄送到前端。
        """
        if self.refusal:
            if self.answer:
                raise ValueError("refusal=True 时 answer 必须为空串，不得残留任何补写内容")
            if not self.refusal_reason:
                raise ValueError("refusal=True 时 refusal_reason 必须非空（not_covered 或 no_evidence）")
        return self
