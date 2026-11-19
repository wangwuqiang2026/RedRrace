"""稠密向量三档后端与响应完整性断言（阶段二 T2）的测试。

出处：task2-brief.md、plan 阶段二步骤 3 与 **3b**（`.superpowers/sdd/plan/phase2-text.md:56-73`）、
决策记录 005 第四节（三档降级）/ 第七节 7.3-3（静默空返回陷阱）/ 第八节更正表、
007 第三节（批量 25 / 单行 131,072 / 整批 400）、第四节（text_type 纪律）、第六节（禁止逐位相等断言）。

覆盖 brief 的五项响应完整性断言（规范 4.4 ①～⑤）、三档行为（4.1、4.12、4.13）、
批量上限与发送前预检（4.5）、暴露给 T3 的向量配置签名材料（4.9）、重试纪律（4.11）。

全部用例**不联网、不调付费 API**（规范 5.17）：HTTP 层一律注入 `httpx.MockTransport` 替身，
真实 key 不出现在本文件（规范 8.6）。「确实没被调用」用替身的计数断言（规范 5.18）。
依规范 5.10 / 4.10，本文件**不得**出现「同参数两次调用向量逐位相等」这类断言（实测 cos=0.999095）。
"""

from __future__ import annotations

import dataclasses
import hashlib
import importlib.machinery
import json
import math
import sys
import types

import httpx
import pytest
from helpers import CONFIG_ENV_KEYS

from app.core.config import Config
from app.retrieval.embedding import (
    ApiEmbedder,
    EmbeddingResult,
    LocalEmbedder,
    StubEmbedder,
    VectorSignature,
    build_embedder,
    cosine,
    estimate_tokens,
)
from app.retrieval.errors import EmbeddingResponseError

DIM = 1024


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """宿主环境变量不得影响默认值断言（规范 5.5：键名从 Config.model_fields 派生，不手抄）。"""
    for key in CONFIG_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def cfg(**over) -> Config:
    """api 档的最小可用配置；密钥一律假值（规范 8.6 禁止任何真实 key 进入代码与测试）。"""
    base = {
        "embedding_backend": "api",
        "embedding_base_url": "https://mock.example/v1",
        "embedding_api_key": "sk-test-not-a-real-key",
        "embedding_model": "qwen3.7-text-embedding-flash",
        "embedding_dim": DIM,
    }
    base.update(over)
    return Config(**base)


def vector(value: float = 0.01, dim: int = DIM) -> list[float]:
    """一条形态正常的向量：分量非零且不全相等，避免被全零检查误伤（只作结构占位，不比数值）。"""
    return [value + i * 1e-6 for i in range(dim)]


def ok_payload(n: int, texts: list[str] | None = None, dim: int = DIM, text_type: str | None = None) -> dict:
    """服务端正常响应的替身体：条数与请求一致、每条维度正确、无空数组。"""
    data = [{"index": i, "embedding": vector(0.01 + i / 100, dim)} for i in range(n)]
    if text_type is not None:
        for item in data:
            item["text_type"] = text_type
    return {"data": data, "model": "qwen3.7-text-embedding-flash", "usage": {"total_tokens": 7 * n}}


class Recorder:
    """传输层替身：记录每一次请求的 URL / 请求体 / 头，并按脚本返回响应（规范 5.18 的计数依据）。"""

    def __init__(self, respond=None):
        self.requests: list[dict] = []
        self._respond = respond or ok_payload

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        self.requests.append({"url": str(request.url), "body": body, "headers": dict(request.headers)})
        return httpx.Response(200, json=self._respond(len(body["input"]), body["input"]))

    @property
    def calls(self) -> int:
        return len(self.requests)


def api_with(respond=None, config: Config | None = None) -> tuple[ApiEmbedder, Recorder]:
    """构造一个走 MockTransport 的 ApiEmbedder——绝不触网（规范 5.17）。"""
    rec = Recorder(respond)
    embedder = ApiEmbedder(
        config if config is not None else cfg(), transport=httpx.MockTransport(rec.handler)
    )
    return embedder, rec


# ── 接口地基：产出物形状与三档共同方法面（T3 照此消费，依 6.11 字段名钉死）────────────────
def test_embedding_result_fields_are_locked():
    """EmbeddingResult 是 T3 直接消费的产出物，字段名一经合并不得改删（规范 6.1、5.12）。

    不钉住会怎样：`build_index.py` 按 `result.vectors` / `result.dense_available` 取值，
    改名后它拿到 AttributeError，或被 `getattr(..., None)` 兜成「没有向量」却继续建索引
    ——正是规范 4.4 要挡的那类静默降质。
    """
    assert {f.name for f in dataclasses.fields(EmbeddingResult)} == {
        "vectors",
        "backend_name",
        "dense_available",
        "total_tokens",
        "requests",
        "text_types",
    }


def test_vector_signature_fields_are_locked():
    """VectorSignature 是索引第二个指纹的材料（规范 4.9），键名同时被 threshold.json 的标定条件复用。"""
    assert {f.name for f in dataclasses.fields(VectorSignature)} == {
        "backend",
        "model",
        "dim",
        "base_url_hash",
        "text_types",
        "digest",
    }
    sig = StubEmbedder().vector_signature()
    assert set(sig.as_dict()) == {
        "backend",
        "model",
        "dim",
        "base_url_hash",
        "text_type_document",
        "text_type_query",
        "digest",
    }, "落盘键名必须展开成两侧独立键，否则 JSON 里是个元组、报告读不懂"


def test_embedding_result_is_frozen():
    """产出物不可变（规范 2.7：进程内中间产物用 frozen dataclass）。

    为什么这条重要：向量的唯一权威持有者是 SQLite 索引；若结果对象可就地改写，
    某处把 vectors 换掉而 backend_name 仍是 "api"，就造出「本地冒充云端向量」的伪证据。
    """
    res = EmbeddingResult(vectors=[vector()], backend_name="stub", dense_available=False)
    with pytest.raises(dataclasses.FrozenInstanceError):
        res.backend_name = "api"  # type: ignore[misc]


def test_three_backends_share_the_same_call_surface():
    """三档必须同时存在且方法面一致（全局约束 6「付费云服务不得为唯一路径」、规范 2.8）。

    不一致的后果：装配层只能靠 if 分支选档，那正是规范 4.13 禁止的隐式换档写法。
    """
    surface = {"embed_documents", "embed_query", "vector_signature"}
    for cls in (ApiEmbedder, LocalEmbedder, StubEmbedder):
        own = {n for n, _ in vars(cls).items() if not n.startswith("_")}
        assert surface <= own, f"{cls.__name__} 缺 {sorted(surface - own)}，三档接口不同形"


# ── stub 档：不得伪造 0 向量冒充真向量（brief 第 21 行、规范 4.12、8.10）──────────────────
def test_stub_declares_dense_unavailable_without_faking_vectors():
    """stub 档必须让 T3 一眼区分「这是 stub」与「api 失败」。

    危害口径：伪造 0 向量的话，0 向量的余弦相似度恒为 0，会被阈值标定当成「确实不相关」的负例吸收掉，
    标出来的 tau 从此偏高一侧，拒答开始误伤正例（规范 4.12「宁可失败也不交半成品」）。
    """
    res = StubEmbedder().embed_documents(["某条检索串"])
    assert res.dense_available is False, "stub 必须显式声明稠密通道不可用，否则降级线无人知晓"
    assert res.backend_name == "stub"
    assert res.vectors == [], "stub 不得返回任何向量（含 0 向量）冒充真向量"


def test_stub_still_rejects_blank_inputs():
    """降级线也走同一条数据质量闸门：stub 放行空串的话，切回 api 时同一条语料又会炸（依 4.12）。"""
    with pytest.raises(ValueError, match="空或纯空白"):
        StubEmbedder().embed_documents(["有效串", "   "])


# ── 断言①：返回条数必须等于请求条数（规范 4.4-①）───────────────────────────────────────
def test_embedder_rejects_count_mismatch():
    """HTTP 200 但少给一条 → 显式报错，禁止填空值继续建索引（步骤 3b 原文的第二例）。

    少了条目还继续，等于索引里某条检索串拿的是别的条目的向量：命中会指到错误出处，
    而 `/api/ask` 仍返回格式完整的答案（004 §三-1 描述的同一形态）。
    """

    def short(total: int, texts: list[str]) -> dict:
        return {"data": [{"index": 0, "embedding": vector()}], "usage": {"total_tokens": 3}}

    embedder, rec = api_with(respond=short)
    with pytest.raises(EmbeddingResponseError, match="向量响应不完整"):
        embedder.embed_documents(["甲检索串", "乙检索串"])
    assert rec.calls == 1, "残缺响应不得自动重试（重试只在网络/超时/限流分支，见 4.11）"


def test_count_mismatch_is_not_masked_by_reordered_index_field():
    """服务端回显的 `index` 顺序与请求顺序无关：本实现按位置取，故条数必须严格相等。

    为什么单独测：若实现改用 `data[i]["index"]` 做映射而又不校验集合完整，
    缺一条时会静默产出更短的列表（zip 截断），T3 拿到「条数对了」的假象。
    """

    def shuffled(total: int, texts: list[str]) -> dict:
        return {
            "data": [{"index": total - 1 - i, "embedding": vector(0.02 + i)} for i in range(total)],
            "usage": {"total_tokens": 3},
        }

    embedder, _ = api_with(respond=shuffled)
    res = embedder.embed_documents(["甲", "乙", "丙"])
    assert len(res.vectors) == 3, "条数相等即通过，不因 index 乱序而丢条目"


# ── 断言②：每条维度必须等于 embedding_dim（规范 4.4-②）────────────────────────────────
def test_embedder_rejects_wrong_dimension():
    """维度不符即报错。依据 007 六-3：`dimensions` 是 MRL 前缀截断而非独立模型，
    768 维向量与 1024 维不等价，混进同一张表会让相似度分布整体挪动。
    """

    def wrong_dim(total: int, texts: list[str]) -> dict:
        return {"data": [{"index": i, "embedding": vector(dim=768)} for i in range(total)],
                "usage": {"total_tokens": 3}}

    embedder, _ = api_with(respond=wrong_dim)
    with pytest.raises(EmbeddingResponseError, match="维度"):
        embedder.embed_documents(["某条检索串"])


def test_embedder_rejects_non_numeric_component():
    """分量必须是数值：null 或字符串数字会让下游点积抛裸 TypeError，运维查不到成因（规范 4.14）。"""

    def bad_component(total: int, texts: list[str]) -> dict:
        vec = vector()
        vec[5] = None  # type: ignore[list-item]
        return {"data": [{"index": 0, "embedding": vec}], "usage": {"total_tokens": 3}}

    embedder, _ = api_with(respond=bad_component)
    with pytest.raises(EmbeddingResponseError, match="不是数值"):
        embedder.embed_documents(["某条检索串"])


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"], ids=["nan", "inf", "neg_inf"])
def test_embedder_rejects_non_finite_component(token):
    """NaN/Inf 分量会穿过五项断言：HTTP 200、条数/维度对、非空、不全零，但 cos 变 NaN（I-2）。

    用 `httpx.Response(content=...)` 而不是 `json=...`：httpx 默认 `allow_nan=False` 会在替身里
    先抛 ValueError，那样测的就是替身而不是生产代码（评审 task2-verdict.md I-2 的取证提示）。
    """
    vec = vector()
    vec[5] = float(token)
    payload = json.dumps({"data": [{"index": 0, "embedding": vec}], "usage": {"total_tokens": 3}})
    # json.dumps 默认也输出 NaN/Infinity 字面量（allow_nan=True），正是要模拟的网关透传形态。
    body = payload.replace("NaN", "NaN").replace("Infinity", "Infinity")

    def bad_finite(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode("utf-8"), headers={"content-type": "application/json"})

    embedder = ApiEmbedder(cfg(), transport=httpx.MockTransport(bad_finite))
    with pytest.raises(EmbeddingResponseError, match="不是有限数值") as exc:
        embedder.embed_documents(["某条检索串"])
    assert "[5]" in str(exc.value), "必须点名是哪一条的第几个分量（依 4.14 措辞分道）"


# ── 断言③：无空数组（规范 4.4-③，步骤 3b 逐字测试形态）────────────────────────────────
def test_embedder_rejects_silent_empty_vectors():
    """官方明示兼容接口传 `output_type=sparse` 时「返回 HTTP 200，但 embedding 结果为空」（005 §7.3-3）。

    只看 status_code 过关的话，稠密通道变成零命中却报告成功，混合检索静默退化成 BM25-only，
    而拒答阈值是按相似度标定的——判定从此悄悄失真。
    """

    def empty_array(total: int, texts: list[str]) -> dict:
        return {"data": [{"index": 0, "embedding": []}] * total, "usage": {"total_tokens": 3}}

    embedder, rec = api_with(respond=empty_array)
    with pytest.raises(EmbeddingResponseError, match="空数组"):
        embedder.embed_documents(["某条检索串"])
    assert rec.calls == 1, "残缺响应不得自动重试：原样重发只会再烧一遍 token"


def test_embedder_rejects_missing_embedding_key():
    """`data` 里压根没有 embedding 字段属同一族残缺，不得当成另一条路放过。"""

    def missing_key(total: int, texts: list[str]) -> dict:
        return {"data": [{"index": 0}] * total, "usage": {"total_tokens": 3}}

    embedder, _ = api_with(respond=missing_key)
    with pytest.raises(EmbeddingResponseError, match="空数组"):
        embedder.embed_documents(["某条检索串"])


def test_embedder_rejects_all_zero_vector():
    """全零向量等价于「没有方向」：cos 恒为 0，会被标定当成真实负例（规范 5.10 允许的四类检查之一）。

    实测正常输出 1024 个分量全非零（007 第二节），所以全零只可能来自残缺响应或上游填空值。
    """

    def zero_vec(total: int, texts: list[str]) -> dict:
        return {"data": [{"index": 0, "embedding": [0.0] * DIM}], "usage": {"total_tokens": 3}}

    embedder, _ = api_with(respond=zero_vec)
    with pytest.raises(EmbeddingResponseError, match="全零"):
        embedder.embed_documents(["某条检索串"])


@pytest.mark.parametrize(
    "payload",
    [[{"embedding": vector()}], {"usage": {"total_tokens": 1}}, {}],
    ids=["list-body", "no-data", "empty-object"],
)
def test_embedder_rejects_malformed_envelope(payload):
    """响应体不是对象、或缺 `data` 键 → 同一句「向量响应不完整」，不留给下游 KeyError（依 4.2 归一）。"""
    embedder, _ = api_with(respond=lambda total, texts: payload)
    with pytest.raises(EmbeddingResponseError, match="向量响应不完整"):
        embedder.embed_documents(["某条检索串"])


# ── 断言④：空 / 纯空白输入客户端先拒（规范 4.4-④，007 六-2）───────────────────────────
@pytest.mark.parametrize(
    "bad", ["", "   ", "\t", "\n", " \u3000 ", "\r\n"],
    ids=["empty", "spaces", "tab", "newline", "ideographic-space", "crlf"],
)
def test_blank_input_is_rejected_before_any_request(bad):
    """实测 `input=[""]` 返回 HTTP 200 且 1024 个分量全非零（007 六-2）：服务端不报警。

    「垃圾进、正常出」防不住，所以必须在客户端拦下。`rec.calls == 0` 是规范 5.18
    要求的计数证据——不能靠「耗时短」反推没发请求。
    """
    embedder, rec = api_with()
    with pytest.raises(ValueError, match="空或纯空白"):
        embedder.embed_documents(["有效检索串", bad])
    assert rec.calls == 0, "预检必须发生在发送之前，否则整批已被拖垮（007 三-3）"


def test_blank_query_is_rejected_before_any_request():
    """查询侧同样拦：空问句拿到的向量无语义，闸门会拿它比出一个「看起来正常」的最高分。"""
    embedder, rec = api_with()
    with pytest.raises(ValueError, match="空或纯空白"):
        embedder.embed_query("   ")
    assert rec.calls == 0


def test_empty_input_list_is_rejected_not_reported_as_dense_available():
    """空列表不能返回 `vectors=[] + dense_available=True`（I-4，规范 4.12/8.15）。

    T3 按 claim 拼装检索串时若上游过滤成空集（空库 / `--rebuild` 打到空表），当前实现
    批循环 `range(0,0,size)` 不产生批次，返回「成功」但零向量：索引建成空表却报告稠密可用，
    与 8.15「禁止空索引静默返回 0 条再落进拒答」同族。措辞须与空白串分道（4.14）。
    """
    embedder, rec = api_with()
    with pytest.raises(ValueError, match="检索串集合为空") as exc:
        embedder.embed_documents([])
    assert rec.calls == 0, "空列表应在发送前就被拦住（5.18）"
    assert "空或纯空白" not in str(exc.value), "空列表与空白串是两种成因，措辞须分道（4.14）"


def test_stub_also_rejects_empty_input_list():
    """降级线同样不能把「没有东西可索引」伪装成成功（I-4，规范 4.12）。"""
    with pytest.raises(ValueError, match="检索串集合为空"):
        StubEmbedder().embed_documents([])


def test_batch_order_is_preserved_and_duplicates_kept():
    """重复文本必须各得一条向量：去重会让 T3 的 claim_id → 向量映射错位（宁可多花 token 也不错位）。"""
    embedder, rec = api_with()
    res = embedder.embed_documents(["同一句", "另一句", "同一句"])
    assert rec.calls == 1, "三条应落在同一个批次里（默认 batch_size=16）"
    assert len(res.vectors) == 3, "去重会把 3 条压成 2 条，条数不再等于请求条数"
    assert rec.requests[0]["body"]["input"] == ["同一句", "另一句", "同一句"], "顺序即 claim 顺序，不得重排"


# ── 断言⑤：text_type 两侧显式进请求体，非法值转显式配置错误（规范 4.4-⑤，007 第四节）────
def test_document_and_query_send_explicit_text_type():
    """漏传 text_type 时两端点默认值相反（兼容层=query、原生=document），同一模型产出 cos≈0.925
    的另一套向量且全程 200（007 四）。两处都必须显式出现在请求体里——brief 要求的正是这个断言形态。
    """
    embedder, rec = api_with()
    embedder.embed_documents(["入库检索串"])
    embedder.embed_query("查询串")
    assert rec.calls == 2
    doc_body, query_body = rec.requests[0]["body"], rec.requests[1]["body"]
    assert doc_body.get("text_type") == "document", "入库侧必须显式带 document"
    assert query_body.get("text_type") == "query", "查询侧必须显式带 query"


def test_effective_text_type_pair_is_readable_without_sending():
    """plan:1097 ① 要求自检能打印「向量请求**实际发出的** text_type 值」，与配置不符即判失败。

    为什么单独暴露而不只靠 vector_signature：签名里的 `未声明` 是给指纹用的口径，
    而自检要区分「确实不传」与「本该传却没传」，所以这里给 None 原值 + 一个布尔判据。
    """
    embedder, _ = api_with()
    assert embedder.effective_text_types == ("document", "query")
    blank, _ = api_with(config=cfg(embedding_text_type_document="", embedding_text_type_query=""))
    assert blank.effective_text_types == (None, None), "留空必须是 None（真的不发该字段），不是空串"
    assert blank.text_type_declared is False and embedder.text_type_declared is True


def test_illegal_server_400_becomes_an_explicit_config_error():
    """服务端对非法 text_type 回显 `its value should be in ['document', 'query']`（007 四末条）。

    这类 400 的成因是配置拼错，而不是入参越界，所以报错措辞必须指向配置文件；
    与「超长导致的 400」共用一句提示的话，运维会去查语料而实际该查 .env（规范 4.14）。
    """

    def bad_text_type(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"error": {"message": "this model's text_type its value should be in ['document', 'query']"}}
        )

    embedder = ApiEmbedder(cfg(), transport=httpx.MockTransport(bad_text_type))
    with pytest.raises(EmbeddingResponseError, match="EMBEDDING_TEXT_TYPE") as exc:
        embedder.embed_documents(["某条检索串"])
    assert "超出 token 预检线" not in str(exc.value), "不得把配置拼错说成入参越界"


@pytest.mark.parametrize("side", ["embedding_text_type_document", "embedding_text_type_query"])
def test_illegal_config_text_type_is_rejected_at_construction(side):
    """非法值（首字母大写的 Document、简写 quer）在服务端是 400 并回显
    `its value should be in ['document','query']`（007 四）。本项目在构造期就转成显式配置错误：
    不重试、不忽略、不回退默认值——静默回退等于换向量空间且不报错，而省下的是一次必然失败的付费请求。
    """
    with pytest.raises(RuntimeError, match="不在合法取值") as exc:
        ApiEmbedder(cfg(**{side: "Document" if "document" in side else "quer"}))
    assert ".env.example" in str(exc.value), "要给出可执行的补齐路径（依 4.1 同族纪律）"


def test_empty_text_type_omits_the_field_and_signature_says_undeclared():
    """配置留空表示确实不传该参数（config.py:75-77、规范 4.9）：此时请求体里没有该字段，
    而向量配置签名必须记「未声明」，让索引判过期、阈值重标，不得静默沿用（007 十一）。
    """
    embedder, rec = api_with(config=cfg(embedding_text_type_document="", embedding_text_type_query=""))
    sig = embedder.vector_signature()
    assert sig.text_types == ("未声明", "未声明"), "置空不等于「和默认一样」，签名必须如实记录"
    embedder.embed_documents(["某条检索串"])
    assert "text_type" not in rec.requests[0]["body"], "留空即真的不传，而不是传空串"


def test_server_echoed_text_type_mismatch_is_rejected():
    """响应回显的 text_type 与请求不一致 → 说明请求里的该参数没生效（被供应商改写），当场报错。

    为什么值得拦：007 第四节的事故形态正是「你以为传了 document，实际按 query 算了」，
    而两次调用都不报错，只有比对回显才能发现向量空间已被换掉。
    """

    def echoed_other_side(total: int, texts: list[str]) -> dict:
        return ok_payload(total, texts, text_type="query")

    embedder, _ = api_with(respond=echoed_other_side)
    with pytest.raises(EmbeddingResponseError, match="回显"):
        embedder.embed_documents(["某条检索串"])


# ── 批量与上限：服务端实测 25，不得把 21～25 判为非法（规范 4.5，007 三-1）───────────────
@pytest.mark.parametrize("n", [1, 16, 20, 21, 25, 26, 40], ids=lambda v: f"n={v}")
def test_batch_sizes_follow_config_batch_size_without_rejecting_21_to_25(n):
    """切批只按 `embedding_batch_size`（默认 16），**不含任何「最大 20」的合法性判断**。

    官方文档称单次最大 20 行，该部署实测硬边界为 25（26 才 400，007 三-1）；
    若照官方数字写校验，21～25 条的批次会被客户端提前拒掉，反复重试白烧 token（规范 4.5 末段）。
    """
    sizes: list[int] = []

    def spy(total: int, texts: list[str]) -> dict:
        sizes.append(total)
        return ok_payload(total, texts)

    embedder, rec = api_with(respond=spy)
    res = embedder.embed_documents([f"检索串{i}" for i in range(n)])
    expected = [16] * (n // 16) + ([n % 16] if n % 16 else [])
    assert sizes == expected, f"切批结果 {sizes} 与默认 16 不符"
    assert len(res.vectors) == n
    assert rec.calls == len(expected)


def test_config_batch_size_above_default_is_honored_up_to_server_limit():
    """把 batch 配到 25（服务端实测硬边界）也必须照用：证明代码里没有隐藏的 ≤20 判断。"""
    sizes: list[int] = []

    def spy(total: int, texts: list[str]) -> dict:
        sizes.append(total)
        return ok_payload(total, texts)

    embedder, _ = api_with(respond=spy, config=cfg(embedding_batch_size=25))
    embedder.embed_documents([f"检索串{i}" for i in range(25)])
    assert sizes == [25], "25 条一批必须放行（007 三-1：25 条 OK、26 条才 400）"


def test_query_side_rejects_a_list():
    """查询侧一次一问句：把多条塞进 embed_query 属于用法错误，须报错而不是静默当 document 处理。"""
    embedder, _ = api_with()
    with pytest.raises(ValueError, match="单个字符串"):
        embedder.embed_query(["甲", "乙"])  # type: ignore[arg-type]


# ── 发送前逐条 token 预检（规范 4.5，007 三-2/3）───────────────────────────────────────
def test_over_long_line_is_caught_client_side_and_names_the_offender():
    """同批混入一条超长会**整批 400、count=0**（007 三-3），所以「先发再看」一损俱损。

    报错必须点名是哪一条（下标）以及近似 token 数，否则采编面对整批失败只能猜（依 4.14）。
    """
    long_text = "讲习所" * 50_000  # 15 万汉字级，远超 128,000 的经验线
    embedder, rec = api_with()
    with pytest.raises(ValueError, match="超出 token 预检线") as exc:
        embedder.embed_documents(["正常检索串", long_text, "另一条正常串"])
    assert "[1]" in str(exc.value), "必须点名越界的是哪一条"
    assert rec.calls == 0, "预检不过即不发请求，避免整批陪葬"


def test_token_estimate_never_undercounts_either_script():
    """近似口径的硬判据是「CJK 一字一 token、非 CJK 每 4 字符 1 token 向上取整、两侧相加」。

    为什么改这条（原测试口径写错、实现没写错）：上一版断言 `estimate_tokens(latin) > len(latin)/2`，
    即要求英文估算值 ≥ 字符数的一半。那个方向不是「保守」，而是**高估到离谱**：主流 BPE 对英文
    约 3.6～4 字符/token（本任务真实冒烟实测：78 字符 / 20 token ≈ 3.9），所以「每 4 字符 1 token」
    已经贴着服务端口径；再往上调就会把本来能过的批次在客户端拦掉，反而伤及召回覆盖。
    brief 的原话是「近似口径要在 docstring 写明并留余量，不得假装是服务端口径」——**余量落在
    预检线**（128,000 vs 服务端实测 131,072，见 config.py:78-80），不落在计数倍数上。
    真正的危害只有低估（客户端放行 → 服务端整批 400、count=0，007 三-2/三-3）。
    因此本条钉的是可判定的定义式不变式，而不是某个倍数。
    """
    cjk = "师范讲习所于一九二五年创设"
    assert estimate_tokens(cjk) == len(cjk), "中文一字一 token 是本口径的定义，不得改成字数除以 2"

    latin = "RedTrace citation-anchored knowledge base " * 400
    # 拉丁侧就是每 4 字符 1 token（向上取整）；改动除数必须同步本断言与 estimate_tokens docstring。
    assert estimate_tokens(latin) == -(-len(latin) // 4), "拉丁侧口径就是每 4 字符 1 token，改动须同步本断言"
    mixed = cjk + "abcd"
    assert estimate_tokens(mixed) == len(cjk) + 1, "混排必须两侧相加，不能互相吞掉计数"

    # 向上取整而非向下：1～4 个拉丁字符至少算 1 token，否则短串一律算 0 就永远不越界。
    assert estimate_tokens("a") == 1 and estimate_tokens("abcd") == 1 and estimate_tokens("abcde") == 2
    assert estimate_tokens("") == 0, "空串的拦截由断言④负责，估算本身给 0 而不是报错"


def test_token_estimate_counts_cjk_punctuation_fullwidth_and_kana_as_one_each():
    """中文标点、全角拉丁、假名都按一字一 token 计——这是引文混排串的主形态（I-1）。

    检索串由「卡片名 + 谓词 + 取值 + 原文引文」拼成，引文必带中文标点。旧口径把 `
    ，。、《》「」；：？！（）…—` 与全角/假名塞进「每 4 字符 1 token」支，
    混排串的估算甚至低于纯汉字串（评审实测 109,275 < 94,000+标点），
    客户端放行 → 服务端整批 400、count=0（007 三-3）。
    """
    punctuation = "，。、《》「」；：？！（）…—"
    assert estimate_tokens(punctuation) == len(punctuation), "中文标点须一字一 token，不得落进 4:1 支"
    fullwidth = "ＡＢＣＤＥ"
    assert estimate_tokens(fullwidth) == len(fullwidth), "全角拉丁须一字一 token"
    hiragana = "あなたは日本語を勉強しています"
    assert estimate_tokens(hiragana) == len(hiragana), "平假名须一字一 token"
    katakana = "カタカナ"
    assert estimate_tokens(katakana) == len(katakana), "片假名须一字一 token"

    # 主形态：汉字 + 中文标点的引文串——估算必须等于总字符数，不得被标点拉低 4 倍。
    quote = "讲习所，成立于一九二五年。" * 100
    assert estimate_tokens(quote) == len(quote), "引文混排串一字一 token，估算不得被标点拉低"


def test_precheck_blocks_a_batch_at_the_configured_line_not_beyond_it():
    """具体危害用例：只要有一条估算越过配置线就必须拦住，且一次请求都不发（依 4.5、5.18）。

    边界两侧各测一次：判据必须是 `>` 而不是 `>=`，否则恰好等于预检线的合法检索串会被误拦，
    而那条线本身已经是相对服务端 131,072 留过余量的经验值（config.py:78-80）。
    """
    limit = 40
    exact_over = "讲" * (limit + 1)  # 一字一 token，恰好越线一个
    embedder, rec = api_with(config=cfg(embedding_max_tokens_per_line=limit))
    with pytest.raises(ValueError, match="超出 token 预检线") as exc:
        embedder.embed_documents(["正常检索串", exact_over])
    assert str(limit + 1) in str(exc.value), "报错要点名近似 token 数，供人核对口径"
    assert rec.calls == 0, "预检不过即不发请求，避免整批陪葬"

    at_limit = "讲" * limit
    embedder2, rec2 = api_with(config=cfg(embedding_max_tokens_per_line=limit))
    embedder2.embed_documents([at_limit])
    assert rec2.calls == 1, "恰好等于预检线必须放行（判据是 >，不是 >=），否则余量方向反了"


def test_precheck_line_comes_from_config_not_hardcoded():
    """预检线取 `embedding_max_tokens_per_line`（默认 128,000，服务端实测 131,072 留余量）。

    写成硬编码的话，换供应商或换部署（005 §7.4「供应商不绑定」）就得改代码而不是改配置。
    """
    embedder, rec = api_with(config=cfg(embedding_max_tokens_per_line=10))
    with pytest.raises(ValueError, match="超出 token 预检线"):
        embedder.embed_documents(["这句在收紧的预检线下就越界了"])
    assert rec.calls == 0


# ── 配置缺失：构造即 RuntimeError 并点名环境变量（规范 4.1、4.13）────────────────────────
@pytest.mark.parametrize(
    "field,env_name",
    [
        ("embedding_base_url", "EMBEDDING_BASE_URL"),
        ("embedding_api_key", "EMBEDDING_API_KEY"),
        ("embedding_model", "EMBEDDING_MODEL"),
    ],
    ids=["base_url", "api_key", "model"],
)
def test_api_embedder_reports_missing_env_names(field, env_name):
    """缺任一必需配置即在构造时抛错，点名缺哪个环境变量并给出补齐路径（范式 extract.py:154-172）。

    不点名会怎样：运维看到「初始化失败」去查网络和语料，实际该查的是 .env 里那一行留空了。
    """
    with pytest.raises(RuntimeError) as exc:
        ApiEmbedder(cfg(**{field: ""}))
    msg = str(exc.value)
    assert env_name in msg, "必须点名环境变量名"
    assert "为空" in msg, "必须说明是配置为空，而不是笼统的初始化失败"
    assert ".env.example" in msg, "必须给出可执行的补齐路径"
    assert "不会自动切换" in msg, "必须告知降级要靠显式选档（规范 4.13）"


def test_api_embedder_does_not_fall_back_to_stub_or_local():
    """缺 key 只能抛错：不许返回空向量冒充成功，也不许自己换成 stub/local（规范 4.1、4.13、8.10）。"""
    with pytest.raises(RuntimeError):
        ApiEmbedder(cfg(embedding_api_key=""))
    assert StubEmbedder().embed_documents(["同一条检索串"]).dense_available is False, (
        "桩件路径可用，且只有调用方显式构造才走它"
    )


@pytest.mark.parametrize(
    "over,needle",
    [
        ({"embedding_dim": 0}, "embedding_dim"),
        ({"embedding_dim": -1}, "embedding_dim"),
        ({"embedding_batch_size": 0}, "embedding_batch_size"),
        ({"embedding_timeout_s": 0}, "embedding_timeout_s"),
        ({"embedding_timeout_s": -1}, "embedding_timeout_s"),
        ({"embedding_max_tokens_per_line": 0}, "embedding_max_tokens_per_line"),
    ],
    ids=["dim0", "dim_neg", "batch0", "timeout0", "timeout_neg", "precheck0"],
)
def test_bad_numeric_config_fails_at_construction(over, needle):
    """数值型配置必须为正：这些值一旦非正会让对应断言变成永真或永假（依 2.15 显式区间），
    当场拦住才能让运维一眼看到是哪个配置项不合理，而不是在最深处炸 numpy / httpx。
    """
    with pytest.raises(RuntimeError, match=needle):
        ApiEmbedder(cfg(**over))


# ── local 档：显式配置但依赖/权重缺失 → 明确报错，禁止隐式退回 api 或 stub（brief 第 20 行）─
def test_local_embedder_names_the_missing_dependency(monkeypatch):
    """本阶段不装 `[retrieval]` extra、不下载权重（规范 8.3），所以 local 档此刻必然报依赖缺失。

    报错必须点名装什么（`pip install -e ".[retrieval]"`，范式 2.18 的延迟导入 + 可安装提示），
    否则用户不知道该补哪一步。
    """
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(ImportError, match=r"\[retrieval\]"):
        LocalEmbedder(cfg())


def test_local_embedder_reports_missing_weights_not_falling_back(tmp_path, monkeypatch):
    """依赖在、权重加载失败 → 报错点名「权重」与下一步动作，不得退回 api 或 stub（规范 4.13、4.12）。

    用假的模块替身模拟「包已安装」，从而把「缺依赖」与「缺权重」两种成因分开测——
    两者共用一句提示的话，排查就得靠猜（规范 4.14）。
    """

    class FakeModel:
        def __init__(self, name_or_path: str):
            raise OSError(f"无法加载权重：{name_or_path}")

    fake_module = types.ModuleType("sentence_transformers")
    fake_module.__spec__ = importlib.machinery.ModuleSpec("sentence_transformers", loader=None)  # type: ignore[attr-defined]
    fake_module.SentenceTransformer = FakeModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    with pytest.raises(RuntimeError, match="权重") as exc:
        LocalEmbedder(cfg(embedding_model=str(tmp_path / "bge-m3-not-downloaded")))
    assert "不会自动切换" in str(exc.value), "必须显式拒绝隐式换档"
    assert "sentence-transformers" in str(exc.value), "要指出下一步动作"


def test_local_embedder_requires_model_config(monkeypatch):
    """local 档的 EMBEDDING_MODEL 承载权重目录；留空时连「该加载什么」都不知道，必须构造期报错。"""
    fake_module = types.ModuleType("sentence_transformers")
    fake_module.__spec__ = importlib.machinery.ModuleSpec("sentence_transformers", loader=None)  # type: ignore[attr-defined]
    fake_module.SentenceTransformer = lambda name: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    with pytest.raises(RuntimeError, match="EMBEDDING_MODEL"):
        LocalEmbedder(cfg(embedding_model=""))


def test_injected_loader_does_not_bypass_optional_dependency_check(monkeypatch):
    """即使注入 loader，缺可选依赖仍须显式报错（I-3，规范 8.3/4.13）。

    注入点存在的目的是「装了依赖但权重没下载」分支能不联网测到（5.17）；它不该让生产调用方
    在没有任何 sentence-transformers 的机器上把 local 档装作可用，直到 _encode 深处抛
    AttributeError。当前实现 `loader if loader is not None else self._load_sentence_transformer()`
    把依赖检查放在 else 支里，给了 loader 就整段跳过——实测构造成功（评审 I-3）。
    """
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(ImportError, match=r"\[retrieval\]"):
        LocalEmbedder(cfg(), loader=lambda name: object())


# ── 档位选择：build_embedder 只做显式分发，不看有没有 key（规范 4.13）─────────────────────
def test_build_embedder_dispatches_only_by_config(monkeypatch):
    """三档由 `embedding_backend` 一项决定；代码里不得出现 `if not api_key: use_stub()`。

    这里故意给 stub 档一份「配置齐全」的 api 参数：若实现偷偷优先 api，返回的对象类型就会变，
    有 key / 无 key 两台机器行为不同，降级演练时才发现真实路径从未被验证过（规范 4.13 的危害描述）。
    """
    assert isinstance(build_embedder(cfg(embedding_backend="stub")), StubEmbedder)
    assert isinstance(build_embedder(cfg(embedding_backend="api")), ApiEmbedder)
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(ImportError):
        build_embedder(cfg(embedding_backend="local"))


def test_build_embedder_rejects_unknown_backend_value():
    """档位值平时由 Literal 挡住（config.py:20），但绕过校验注入脏值仍须显式报错而不是回落默认档。"""
    c = cfg()
    object.__setattr__(c, "embedding_backend", "cloud")
    with pytest.raises(RuntimeError, match="未知的向量档位"):
        build_embedder(c)


# ── 向量配置签名材料：T3 的第二个指纹照此取（规范 4.9，005 §三-1、007 §四）───────────────
def test_vector_signature_carries_the_four_required_materials():
    """签名材料 = 模型名 + 维度 + 供应商基址哈希 + text_type 两侧组合（005 第八节扩容后的四条）。

    为什么基址只进哈希不进明文：签名会被写进索引文件与阈值文件的标定条件（规范 6.12），
    哈希足以支撑「换端点即判过期」，又不把内部域名原样带进交付物。
    """
    embedder, _ = api_with()
    sig = embedder.vector_signature()
    assert sig.model == "qwen3.7-text-embedding-flash"
    assert sig.dim == DIM
    assert sig.base_url_hash == hashlib.sha256(b"https://mock.example/v1").hexdigest()[:16]
    assert sig.text_types == ("document", "query")
    assert sig.backend == "api"


def test_vector_signature_changes_when_text_type_changes():
    """text_type 与换模型同级：`document-document` 与 `document-query` 把相似度 mean 从 0.3945
    搬到 0.4694、min 从 0.2524 搬到 0.3328（007 四），同一条阈值切掉的候选比例随之改变。
    """
    a, _ = api_with()
    b, _ = api_with(config=cfg(embedding_text_type_query="document"))
    assert a.vector_signature().digest != b.vector_signature().digest, (
        "两侧组合变更必须让签名变化，否则 T3 会沿用旧阈值（规范 4.9）"
    )


def test_vector_signature_digest_is_stable_across_instances():
    """同一组配置两次取签名必须相同（这是配置哈希，不是向量本身，允许逐位比较）。

    注意与规范 5.10 的区别：那条禁的是「同参数两次调用的**向量**逐位相等」；
    签名不经过服务端，稳定性正是索引判过期的前提。
    """
    e1, _ = api_with()
    e2, _ = api_with()
    assert e1.vector_signature().digest == e2.vector_signature().digest
    e3, _ = api_with(config=cfg(embedding_dim=768))
    assert e3.vector_signature().digest != e1.vector_signature().digest


def test_stub_signature_is_marked_no_vector_so_bm25_only_cannot_be_confused():
    """stub 档没有模型与维度可言：签名必须自报 no-vector，否则 T3 会把 BM25-only 索引
    当作「某个 api 档建的索引」而拿 api 档阈值去判它（规范 4.12 的自报口径）。
    """
    sig = StubEmbedder().vector_signature()
    assert sig.backend == "stub"
    assert sig.digest.startswith("no-vector"), "签名前缀即降级标记，报告与自检可直接断言"
    assert sig.model == "none" and sig.dim == 0


def test_local_signature_marks_text_type_undeclared(monkeypatch):
    """LocalEmbedder（bge-m3）无 text_type 参数（007 第四节末条）：签名记「未声明」，
    使「本地档建的索引被 API 档阈值判定」这种跨档混用在签名层面就不同构。

    I-3 之后注入 loader 也必须过依赖守卫：这里先用假模块替身表示「已装 extra」（规范 5.17），
    loader 只用于避免真的下载权重，不能顺带绕过依赖前提。
    """
    fake_module = types.ModuleType("sentence_transformers")
    fake_module.__spec__ = importlib.machinery.ModuleSpec("sentence_transformers", loader=None)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    embedder = LocalEmbedder(cfg(), loader=lambda name: object())
    sig = embedder.vector_signature()
    assert sig.backend == "local"
    assert sig.text_types == ("未声明", "未声明")
    assert sig.digest != ApiEmbedder(cfg()).vector_signature().digest


# ── 请求体形态与重试纪律（规范 4.11）────────────────────────────────────────────────────
def test_request_body_shape_matches_openai_compatible_embeddings():
    """OpenAI 兼容 `/embeddings` 的请求体形态：model + input(+dimensions) + text_type，
    Authorization 走 Bearer。换供应商只动这 6 个配置值、代码不动（005 §7.4「供应商不绑定」）。
    """
    embedder, rec = api_with()
    embedder.embed_documents(["某条检索串"])
    req = rec.requests[0]
    assert req["url"].endswith("/embeddings"), "路径必须落在 OpenAI 兼容的 embeddings 端点"
    body = req["body"]
    assert body["model"] == "qwen3.7-text-embedding-flash"
    assert body["input"] == ["某条检索串"]
    assert body["dimensions"] == DIM, "维度显式传给服务端：MRL 截断下不传就可能拿到别的维度（007 六-3）"
    assert req["headers"]["authorization"] == "Bearer sk-test-not-a-real-key"


def test_network_errors_are_retried_up_to_three_attempts_then_raise():
    """首次 + 重试两次（对齐 extract.py:48 的 MAX_ATTEMPTS=3 口径，规范 4.11）。

    耗尽后必须抛错终止建索引，不得吞异常返回空列表——那是规范 4.1 描述的
    「稠密通道静默返回 []、BM25 独扛、接口 200、日志无异常」。
    """
    attempts: list[int] = []

    def flaky(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) < 3:
            raise httpx.ConnectError("连接被重置")
        return httpx.Response(200, json=ok_payload(1))

    embedder = ApiEmbedder(cfg(), transport=httpx.MockTransport(flaky))
    res = embedder.embed_documents(["某条检索串"])
    assert len(attempts) == 3 and len(res.vectors) == 1, "前两次抖动应被重试吸收，第三次成功"
    assert res.requests == 3, "调用次数要把重试算进去，供阶段八冷机统计（005 §三-3）"


def test_persistent_transport_failure_raises_after_three_attempts():
    """三次都失败 → EmbeddingResponseError 且点名尝试次数与超时配置，不返回空向量冒充成功。"""

    def always_timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("超时")

    embedder = ApiEmbedder(cfg(), transport=httpx.MockTransport(always_timeout))
    with pytest.raises(EmbeddingResponseError, match="3 次尝试") as exc:
        embedder.embed_documents(["某条检索串"])
    assert "embedding_timeout_s" in str(exc.value), "要给出可核对的超时配置线索"


@pytest.mark.parametrize("status", [401, 403, 404, 400], ids=["unauth", "forbidden", "notfound", "badreq"])
def test_client_side_http_status_is_never_retried(status):
    """4xx 里除 429 外都是「配置或入参问题」，重发只会重复失败并白烧 token（依 4.11、8.12 的成本纪律）。"""
    calls: list[int] = []

    def responder(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(status, json={"error": {"message": "upstream said no"}})

    embedder = ApiEmbedder(cfg(), transport=httpx.MockTransport(responder))
    with pytest.raises(EmbeddingResponseError):
        embedder.embed_documents(["某条检索串"])
    assert calls == [1], f"HTTP {status} 不得重试"


def test_rate_limit_and_server_errors_are_retried_then_reported():
    """429 与 5xx 值得重试（限流退避、服务端抖动）；耗尽后报错要点名限流口径（005 §7.1 官方 RPM/TPM）。"""
    calls: list[int] = []

    def throttled(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(429, json={"error": {"message": "Requests rate limit exceeded"}})

    embedder = ApiEmbedder(cfg(), transport=httpx.MockTransport(throttled))
    with pytest.raises(EmbeddingResponseError, match="限流"):
        embedder.embed_documents(["某条检索串"])
    assert len(calls) == 3, "429 应按 MAX_ATTEMPTS 重试后再放弃"


def test_http_status_phrases_differ_by_cause():
    """401 / 404 / 429 / 500 各自的短语与下一步线索必须互不相同（规范 4.14：排查不能靠猜）。"""
    cases = {
        401: ("鉴权失败", "EMBEDDING_API_KEY"),
        404: ("端点不存在", "EMBEDDING_BASE_URL"),
        429: ("限流", "RPM"),
        500: ("服务端错误", "稍后重试"),
    }
    seen_messages: list[str] = []
    for status, (needle, hint) in cases.items():
        def responder(request: httpx.Request, s=status) -> httpx.Response:
            return httpx.Response(s, json={"error": {"message": "upstream said no"}})

        embedder = ApiEmbedder(cfg(), transport=httpx.MockTransport(responder))
        with pytest.raises(EmbeddingResponseError, match=needle) as exc:
            embedder.embed_documents(["某条检索串"])
        assert hint in str(exc.value), f"HTTP {status} 必须给出对应下一步线索"
        seen_messages.append(str(exc.value))
    assert len({m.split("响应片段")[0] for m in seen_messages}) == 4, "四种故障的措辞不得雷同"


def test_response_that_is_not_json_is_reported_as_incomplete():
    """网关偶发返回 HTML 错误页：解析失败归入「向量响应不完整」而不是裸 JSONDecodeError（依 4.2）。"""
    embedder = ApiEmbedder(cfg(), transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html/>")))
    with pytest.raises(EmbeddingResponseError, match="不是 JSON"):
        embedder.embed_documents(["某条检索串"])


# ── 成本与调用次数记账（供 T3 的报告与阶段八冷机统计消费，005 §三-3）────────────────────
def test_usage_total_tokens_and_request_count_are_recorded():
    """005 第三节第 3 条：冷机指标要分开记录「API 调用次数与输入 token 数」，故 embed() 必须回传。"""
    embedder, _ = api_with()
    res = embedder.embed_documents([f"检索串{i}" for i in range(20)])
    assert res.requests == 2, "20 条按 16 切批应为两次请求"
    assert res.total_tokens == 7 * 20, "usage.total_tokens 必须累加各批，供成本单列记账"
    assert res.text_types == ("document", "query"), "结果里也要带实际生效的组合，供报告直接引用"


def test_stub_records_zero_requests_and_zero_tokens():
    """stub 档不产生任何云端开销，但仍要把 requests=0 显式写出来：
    缺这个字段的话报告里「0 次调用」与「忘了统计」长得一样（规范 4.12、5.18）。
    """
    res = StubEmbedder().embed_documents(["甲", "乙"])
    assert res.requests == 0 and res.total_tokens == 0
    assert res.text_types == ("未声明", "未声明")


def test_no_real_network_transport_in_this_file():
    """本文件所有用例都走注入替身：任何一次真实网络调用都会在这里现形（规范 5.17、5.18）。"""

    def boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError("测试不得触网：请检查是否有用例漏传 transport")

    embedder = ApiEmbedder(cfg(), transport=httpx.MockTransport(boom))
    with pytest.raises(AssertionError, match="不得触网"):
        embedder.embed_documents(["某条检索串"])


# ── 可复现性判据：按 cos 阈值，不按逐位相等（规范 4.10、5.10）────────────────────────────
def test_cosine_reproducibility_is_judged_by_threshold_not_bitwise():
    """规范 4.10 / 5.10 + R18：可复现性按 cos ≥ 0.998 判。

    这条测试的作用是把「判据」本身钉进代码库：T3/T5 若写逐位相等的断言，
    评审能拿本函数与注释说明为什么那样写会随机假红（007 六-1 读数 0.999095，
    T2 真实冒烟读数 0.998869；取 0.999 会随机假红，故 R18 定为 0.998）。
    """
    threshold = 0.998
    a, b, c = [1.0, 0.0], [0.99995, 0.0099], [0.0, 1.0]
    assert cosine(a, b) >= threshold, "近重合向量应判为可复现"
    assert cosine(a, c) < threshold, "正交向量不得被判为可复现（阈值放宽成永真即失去意义）"
    assert math.isclose(cosine(a, a), 1.0, abs_tol=1e-12)


def test_cosine_refuses_degenerate_inputs():
    """全零向量分母为 0、长度不等都会让「相似度」变成一个好看的假数，必须报错（依 8.13）。"""
    with pytest.raises(ValueError, match="全零|分母"):
        cosine([0.0, 0.0], [1.0, 0.0])
    with pytest.raises(ValueError, match="等长"):
        cosine([1.0, 0.0], [1.0, 0.0, 0.0])
