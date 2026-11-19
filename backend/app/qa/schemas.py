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
    """一条带出处的引用：编号 + 断言 + 定位 + 来源。

    `verified` 默认 False（阶段三步骤 1）：未经三层校验的引用不得默认显示「已通过」。
    校验通过后由 `citation.verify_answer()` 回填 True；前端据此决定是否渲染引用标记。
    """

    index: int
    claim: str
    locator: Locator
    source: SourceOut
    verified: bool = False


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
    """提问请求：问题、召回条数、身份（plan 阶段一/三「接口约定」）。

    阶段三新增 `source_ids` / `media_types`（可选来源范围）。**空范围的语义是「不限制」而不是
    「查不到」**（步骤 3b-1）：把空选择当成「搜 0 个来源」会让系统用「知识库没有依据」
    回答一个根本没检索的问题。判定收在 `qa.constants.is_unrestricted()`，测试与流水线共用。
    """

    question: str
    top_k: int = 8
    role: Literal["学生", "教师", "馆员"] = "学生"
    source_ids: list[str] = Field(default_factory=list)
    media_types: list[str] = Field(default_factory=list)


class AnswerOut(BaseModel):
    """回答结构：是否拒答、答案正文、引用列表、冲突组、参考建议、耗时。

    除 `refusal_reason` 外**全部必填**（审查 I2）：简报把它们写成无默认值字段，之前我给了
    默认值，导致 openapi 的 `required` 只剩 `refusal`，前端生成的类型变成 `citations?: Citation[]`
    并被迫到处 `?? []`——契约强比宽松好，后端漏填一个字段就该在序列化前报错，而不是让
    「忘了填」和「确实没有」在前端长得一模一样。
    """

    refusal: bool
    # ruff 的 PYI061 要求把 None 挪出 Literal，故写作 `Literal[...] | None`。
    # JSON Schema 结构为 anyOf[enum(strings), null]，openapi-typescript 解析成
    # `"not_covered" | "no_evidence" | "all_claims_rejected" | null`（阶段三扩了第三个原因码）。
    # 阶段三扩为三种原因码：`all_claims_rejected` = 证据有、但逐句校验后无保留句（步骤 5b-2）。
    refusal_reason: Literal["not_covered", "no_evidence", "all_claims_rejected"] | None = None
    answer: str
    citations: list[Citation]
    conflicts: list[ConflictItem]
    suggestions: list[str]
    elapsed_ms: int
    # 闸门审计字段（步骤 5b-2）：拒答时必须带真实数字，事后能复原「检索是否发生、分数多少、
    # 当时阈值多少」。字段有默认值只为阶段零F 契约兼容；流水线在拒答路径必定覆盖它们。
    retrieved_count: int = 0
    top_score: float | None = None
    threshold: float | None = None
    gate_note: str = ""

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
