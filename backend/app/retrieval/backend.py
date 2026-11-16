"""检索层对外契约：`Hit` 召回结果 + `SearchBackend` 抽象接口（阶段二 T1）。

口径出处：plan 阶段二「接口约定」与步骤 3b、4、4b（`.superpowers/sdd/plan/phase2-text.md:13,49-51,85-100`）、
`.superpowers/sdd/plan/task1-brief.md`，以及 lead 裁决 D4（四分数定名）、D9（类名 `SearchBackend`）、
D13（`Hit` 用 dataclass、本阶段不进 OpenAPI）——见 `.superpowers/sdd/plan/progress.md:51,56,60`。

本文件是整层的接口地基（依 6.7、6.8）：T2 的向量三档、T3 的索引与 `LocalBackend`、T4 的融合重排、
T5 的阈值标定全部按此签名写实现，**字段名与方法名一经合并即不可改、不可删**（依 6.1 准入条件 4；
改名须先让 `tests/test_hit_contract.py` 变红并同步下游）。因此这里只放类型与抽象方法，不放任何检索逻辑。

为什么用 ABC 而不是 `Protocol`（依 2.8 的取舍说明）：2.8 的 Protocol 形态服务于「运行时鸭子替换的多实现」
（如 `Extractor`），而 brief 测试要求 3 明确要求「子类漏实现任一方法即实例化报错」——`Protocol` 不做这层
校验（`isinstance` 只查方法存在与否，不查是否 `NotImplementedError` 空壳）。故抽象基类叫 `SearchBackend`
（裁决 D9），实现类按计划叫 `LocalBackend`（T3 写）、可选适配器 `RagFlowBackend`（本轮 deferred，
见 progress.md:40）。依 2.1 包内一律绝对导入；依 D1 本目录不建 `__init__.py`（保持命名空间包一致）。
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

# ── Hit：一条召回结果，六个语义字段 ────────────────────────────────────────────────
# 四种分数的量纲唯一权威定义在此（依 6.7：其余模块只 import、不自建同义 dataclass）。
# 每行注释写明「量纲 + 可否跨请求比较 + 是否参与闸门」三件事，缺一不可判定（依 4.8、4.6）。
_SCORE_FIELDS = ("score", "dense_score", "sparse_score", "rerank_score")

# 相似度类分数列的取值上界。为什么只有这三列封顶到 1.0、`sparse_score` 不设上界（依 4.8）：
# score / dense_score 是 cos 相似度、rerank_score 是官方口径的 0–1 相对分，越界即说明上游算错了；
# 而 BM25 词频分无上界，强行归一会让它「长得像相似度」，反而诱发拿它比阈值——
# 那正是 §5.23「相关与不相关得分看起来差不多」的成因。锁测试见 test_hit_contract.py。
_UNIT_INTERVAL_FIELDS = ("score", "dense_score", "rerank_score")


def _check_score(name: str, value: float | None) -> None:
    """四个分数列的统一入参校验：要么 `None`（表示这个数不存在），要么是一个可比的真实分值。

    合法取值域按列不同（依 4.8「三种量纲不得混列」）：
    - `score` / `dense_score`：cos 相似度，[0, 1]；
    - `rerank_score`：官方口径的 0–1 相对分，[0, 1]；
    - `sparse_score`：BM25 词频分，**无上界**，只要求非负且可比。
    上界只在前两列加 rerank 列生效，见 `_UNIT_INTERVAL_FIELDS`。

    为什么把「无相似度」建模成 `None` 而不是 `-1` / `nan`（依 4.7、8.14，步骤 4b-2 原文）：
    - `-1` 哨兵混进分数列后，前端出处卡会把两把尺子显示在同一列，出现「0% 却被引用」这类无法解释的观感
      （参考实现 §5.32 实测事故）；
    - `nan` 参与任何比较恒为 False、`inf` 恒为最大，闸门都会静默放行全部候选
      （正是 4.7 描述的「无从判断而全放行」）。
    所以非法值必须当场报错，而不是留给下游猜（呼应 6.3 的「违约对象连构造都过不了」）。

    为什么不拦 `0.0`（对 brief 测试要求 1 的必要更正，理由已写进 task1-report.md）：
    cos 归一后落在 [0,1]，`0.0` 是一个**合法的低相似度**；拿它冒充「没算过」才会让闸门把
    「确实不相关」和「压根没有向量」判成同一回事——而 brief 要的正是后者由 `None` 表达。
    若在此拒绝 0.0，T5 就造不出相似度为 0 的负例，阈值扫描曲线低端出现空洞。

    为什么允许 BM25 分 > 1：`rank_bm25` 的词频分无上界（依 4.8、步骤 4b-2），
    强行归一会让人误以为它能跟 `score` 一起比阈值——那才是 4.8 禁止的混列风险来源。
    """
    if value is None:
        return
    # 为什么这里用 ValueError 而不是 TRY004 建议的 TypeError（行内豁免理由，依 7.7）：
    # 规范 4.2 把「入参不合法」归一为 ValueError 并贯穿全仓（`registry.py:147-152`、`migrate.py:52-53`），
    # 调用方与 CLI 只写 `except ValueError`；此处若抛 TypeError，脏数据会炸穿成裸 traceback，
    # 采编看不到「是哪一条候选、哪一列、该传 None」。类型错误在本项目是**入参校验**而非编程错误。
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(  # noqa: TRY004  依 4.2 入参归一为 ValueError，理由见上方注释
            f"Hit.{name} 必须是 float 或 None（依 4.7：无相似度显式 None），收到 {type(value).__name__}"
        )
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise ValueError(
            f"Hit.{name} = {value!r} 不是可比数值（依 8.14：nan 参与比较恒 False、inf 恒为最大，"
            "两者都会让闸门静默放行全部候选）；该候选没有这个分数请传 None"
        )
    if value < 0.0:
        raise ValueError(
            f"Hit.{name} = {value!r} 为负数（依 4.7、8.14：负数是 -1 哨兵的变体，"
            "会被当成真实低分参与闸门比较）；该候选没有这个分数请传 None"
        )
    # 上界只对相似度类分数成立；sparse_score 不在此列，理由见 _UNIT_INTERVAL_FIELDS 上方注释。
    if name in _UNIT_INTERVAL_FIELDS and value > 1.0:
        raise ValueError(
            f"Hit.{name} = {value!r} 超出 0–1（依 4.8：综合分与稠密分是 cos 相似度、重排分是官方 0–1 相对分，"
            "越界说明上游把 BM25 分或原始 logits 写进了这一列，量纲已混）"
        )


@dataclass
class Hit:
    """一条召回结果：条目编号 + 卡片编号 + 四种分数（plan 阶段二「接口约定」逐字对应）。

    计划原文给的是中文语义名「条目编号、卡片编号、综合分、稠密分、稀疏分、重排分」，
    英文名由裁决 D4 一次定死为 `claim_id / card_id / score / dense_score / sparse_score / rerank_score`，
    锁测试在 `tests/test_hit_contract.py::test_hit_field_names_are_locked`（依 5.12）。

    为什么只有这六个字段（依 brief「只加本阶段确实用的，别提前为阶段三铺字段」）：
    定位所需的 `source_id` / `quote` / `locator` 属于出处九字段，落在 `qa/schemas.SourceOut`（依 6.2
    「HTTP 可见模型只在 qa/schemas.py」），阶段三按 `claim_id` 回表取即可；在检索层重复一份
    等于两套口径并存（依 2.17「禁止复制同义模型」）。`text` 同理不落——正文由 T3 的索引侧持有。

    为什么非 frozen（依 2.7 的分工 + 步骤 4b-1）：重排在融合之后要回填 `rerank_score`；
    4b-1 禁的是回写 `score`，不是禁止写入新字段。frozen 会逼实现另开一个可变包装类，
    反而制造「两份 Hit」的漂移风险。

    闸门唯一尺子是 `Hit.score`（依 4.6）：契约层**不提供** `gate_score()` 之类的取数函数，
    也不提供任何具名构造器——类上多一个产出 Hit 的入口，就多一处把 BM25 分塞进 `score` 列的机会
    （依 4.8）。构造稀疏-only 结果请显式写全六个字段，让「哪一列是 None」在调用点可读。
    比较一律由 T5 的 `calibrated_threshold()` 消费方直接取 `h.score`
    （步骤 5 原文写法 `max(h.score for h in index.search(q, 8))`）。

    为什么全部必填、不给默认值（依 6.4）：除确有缺省语义的字段外不给默认值，
    「忘填」和「确实没有」必须在前端与测试上长得不一样——若 `rerank_score` 有默认值，
    重排通道忘回填与「压根没开重排」就完全同形，规范 4.3 禁止的「界面显示开启、实际空转」再也测不出来。
    """

    claim_id: int
    """事实条目编号，对应 `db/models.py:49` 的 `claims.claim_id`（INTEGER PRIMARY KEY）。"""

    card_id: int
    """所属卡片编号，对应 `db/models.py:38` 的 `cards.card_id`；冲突并列与出处装配按它分组。"""

    score: float | None
    """**综合分**：0–1 相似度量纲，由稠密与融合结果得出（步骤 4b-1）。
    可跨请求比较，且是拒答闸门的唯一取数来源（依 4.6）；T5 的标定测试写 `max(h.score ...)`。
    允许 `None` 是约束 6 / 005 的硬要求：BM25-only 档（`StubEmbedder`、无 key、降级演练）
    确实产不出相似度，此时闸门走「无相似度可用」分支并显式留痕，而不是拿 0.0 冒充低分。"""

    dense_score: float | None
    """稠密向量相似度（0–1 cos）。无向量时为 `None`——`stub` 档与 BM25-only 路径都属合法形态
    （依全局约束 6「付费云服务不得为唯一路径」）。不参与闸门，仅供双通道自检与调试对照（依 5.20）。"""

    sparse_score: float | None
    """BM25 词频分：**量纲与向量相似度不可比**（步骤 4b-2 原文），无上界，故不做 [0,1] 校验。
    该候选无向量相似度时本字段仍照常保留，但 `dense_score` / `score` 取 `None`；
    反过来「有向量、没被 BM25 召回」时本字段为 `None`。禁止用 `-1` 顶替（依 4.7、8.14）。
    稀疏名额上限 `k // 2` 由 T4 在融合处落实（依 4.7），契约层只保证「无分条目可被识别」。"""

    rerank_score: float | None
    """API 重排的 `relevance_score`（0–1）。官方明示「本次请求的相对分数，**不可跨请求比较**」
    （决策记录 006 §三-1），而拒答阈值恰是跨题标定的量，两者性质根本不可混用（依 4.6）。
    未启用重排、`local_lexical` 档、或重排失败回退时为 `None`（依 4.3：回退是默认行为，不是异常路径）。
    **永不参与阈值比较，也绝不回写 `score`**（步骤 4b-1）。"""

    def __post_init__(self) -> None:
        for name in _SCORE_FIELDS:
            _check_score(name, getattr(self, name))


# ── IndexStats：两条通道各自的命中数，供 build_index.py 打印自检 ──────────────────────
@dataclass
class IndexStats:
    """检索后端自检统计。字段名会被 `scripts/build_index.py` 与评测报告脚本复用，不要随手改名
    （依 6.11，范式 `cli.py:55-57` 与其锁测试 `test_cli_stats.py:364-374`）。

    两个通道命中数的键名固定为 `dense_hits` / `sparse_hits`（brief 测试要求 4）：
    步骤 3b 要求打印「稠密 n / 稀疏 m」两条通道各自的命中数，**任一侧长期为 0 即判未生效**
    （全局约束「有降级路径」）。之所以默认 0 而不是 `None`：判据是「== 0」，
    若给 `None`，`stats.dense_hits == 0` 恒为 False，那条自检就变成永真式（依 5.19 反对的写法）。
    """

    dense_hits: int = 0
    """稠密（向量）通道在一次自检查询上的命中条数；长期为 0 → 向量档空转（依 4.12 必须照实打印缺口）。"""

    sparse_hits: int = 0
    """稀疏（BM25 + jieba）通道命中条数；长期为 0 → 分词器或自定义词典未生效（步骤 3b 的中文零命中事故）。"""

    total_docs: int = 0
    """索引内检索串条数；供报告区分「语料规模」与「命中数」，避免拿小样本的满命中当达标。"""

    index_built: bool = False
    """索引是否已构建。依 8.15：不得假设索引已存在，缺索引必须显式报错并提示重建命令，
    禁止空索引静默返回 0 条再落进拒答。本字段就是那句报错的前置判据。"""


# ── SearchBackend：检索层唯一对外契约 ───────────────────────────────────────────────
class SearchBackend(ABC):
    """检索后端抽象接口（裁决 D9：不得复用 `config.RetrievalBackend` 作类名，那是档位别名
    `Literal["local","ragflow"]`，已进 `/api/health`，同名异义会让人把「选哪一档」当成「哪个实现类」）。

    上层 `qa/*` 与 API 只消费 `Hit`，不得越过本接口直接摸索引文件（依 6.8）。
    实现类：`LocalBackend`（T3，自研管线）；`RagFlowBackend` 同接口、本轮 deferred（progress.md:40）。
    三个方法名 `search` / `search_bm25_only` / `search_dense_only` 与 `index_stats`
    在本任务一次性定死，不留给 T3/T4 追加改名（brief「Ruling」+ 依 6.1「可加不可改」）：
    步骤 3b 的测试原文要直接调 `index.search_bm25_only(...)`，等 T3 再加就会跨任务改接口。
    """

    @abstractmethod
    def index(self, *args: Any, **kwargs: Any) -> Any:
        """构建 / 刷新索引。参数留给 T3 决定（DB 路径、切块口径、指纹来源都在其写范围内）。

        为什么不在此钉死签名（依 brief「只定接口契约」+ 规范 6.8「唯一对外契约是 search(...)」）：
        `index()` 不产出跨模块消费的返回值，钉早了只会让 T3 反向来改契约；
        而 `search` 系列的签名是全层地基，必须现在定死。
        契约要求只有一条：实现必须在缺语料 / 缺配置时**显式报错**，不得静默产出空索引（依 8.15、4.12）。
        """

    @abstractmethod
    def search(self, query: str, k: int, *, rerank: bool = True) -> list[Hit]:
        """混合召回主入口：稠密前 `retrieval_dense_top_k` + 稀疏前 `retrieval_sparse_top_k`
        → RRF 融合（常数 `retrieval_rrf_constant`）→ 可选 API 重排 → 取最终 k 条（步骤 4）。

        `rerank` 为仅关键字参数（依 2.16）：调用形态出自步骤 4b 的测试原文
        `index.search(q, 8, rerank=False)`，位置传参会让「是否重排」这种改变分数语义的开关被淹没。
        默认 `True` 与 `rerank_backend="api"` 的默认档位一致（`config.py:83`）。

        硬性契约（依 4.6、步骤 4b-1）：`rerank=True/False` 两次调用返回的 `max(h.score)` 必须相同——
        重排只改排序、只写 `rerank_score`，**不回写 `Hit.score`**；否则步骤 6 标定的阈值静默失效。
        重排不可用时按 4.3 打印 `[重排未生效: <原因>]` 并照融合顺序返回，不抛异常。
        """

    @abstractmethod
    def search_bm25_only(self, query: str, k: int) -> list[Hit]:
        """关掉稠密、只留稀疏的自检通道（步骤 3b 原文测试 `test_sparse_channel_hits_cjk_query` 直接调它）。

        存在的理由不是便利，而是防一类具体事故：全文索引沿用按空格分词时，中文整句被当成一个 token，
        关键词通道对任何中文问句恒返回 0 条，混合检索**静默退化成只剩向量**且日志无人注意（步骤 3b 首段）。
        返回的 `Hit` 其 `dense_score` / `score` 为 `None`、`sparse_score` 有值（依 4.7）。
        """

    @abstractmethod
    def search_dense_only(self, query: str, k: int) -> list[Hit]:
        """与上对称：只留稠密的降级对照通道（依 5.20「双通道必须分别单独跑通，不得只测混合结果」）。

        `embedding_backend="stub"` 时本通道应命中数为 0 并被自检照实打印，
        而不是拿 BM25 的结果冒充稠密命中（依 4.13「代码里不得出现隐式换档分支」、8.10）。
        返回的 `Hit` 其 `sparse_score` 为 `None`。
        """

    @abstractmethod
    def index_stats(self) -> IndexStats:
        """返回两条通道各自的命中数与索引状态，供 `scripts/build_index.py` 打印（步骤 3b 配套要求）。

        返回结构是本契约的一部分：键名 `dense_hits` / `sparse_hits` / `total_docs` / `index_built`
        固定（依 6.11），实现不得改成 dict 自由键名或 tuple，否则报告脚本静默拿到 `KeyError`
        或被 `.get(..., 0)` 兜成 0 命中——又回到「通道空转却没人注意」的原点（依 4.14 要能分辨成因）。
        """
