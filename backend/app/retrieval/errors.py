"""检索层共用异常：`EmbeddingResponseError`、`RerankResponseError`（阶段二 T1，裁决 D3）。

谁 import 它（本模块存在的唯一理由就是「集中一处」）：
- `app/retrieval/embedding.py`（T2 的 `ApiEmbedder.embed()`）——响应完整性五项断言任一不满足时抛
  `EmbeddingResponseError`（规范 4.4；步骤 3b 原文的测试即 `pytest.raises(EmbeddingResponseError)`）；
- `app/retrieval/rerank.py`（T4 的 `ApiReranker.rerank()`）——返回条数与请求不符等残缺响应抛
  `RerankResponseError`（步骤 4 纪律③「缺条目即报错，不得用默认分补齐」）；
- `scripts/build_index.py`（T3）只需 `except (EmbeddingResponseError, RerankResponseError)` 或
  `except RuntimeError` 即可拦住整族外部服务故障。

为什么继承 `RuntimeError` 而不是 `Exception`（依 4.1）：既有代码里「配置缺失 / 后端不可用」一律以
`raise RuntimeError` 落地（范式 `extract.py:154-172` 的 `LlmExtractor.__init__`），装配层与 CLI 按
这一族拦截；若基类改成 `Exception`，上层 `except ValueError` / `except RuntimeError` 都拦不住，
建索引会以裸 traceback 中止，采编看不到「是哪一个环节、要补什么」。锁测试见
`tests/test_hit_contract.py::test_response_errors_are_runtimeerror_subclasses`（依 5.12）。

为什么不复用 `ValueError`（依 4.2 的分工）：4.2 把 **IO / 编码 / 入参**归一为 `ValueError`，
而这两个类描述的是**外部服务的响应残缺**——同一状态码 200 下服务端给了空数组、少了条目或换了维度。
两者混用的话调用方会按「你的输入有问题」提示运维去查语料，实际该查的是 API 响应（依 4.14）。

报错措辞纪律（依 4.14）：两个类的实例化消息必须各自点名所属通道——「向量响应不完整」与
「重排未生效」不得共用一句模糊提示，否则排查靠猜。文案由抛出方拼装，本模块只定类型。
"""

from __future__ import annotations

__all__ = ["EmbeddingResponseError", "RerankResponseError"]


class EmbeddingResponseError(RuntimeError):
    """向量接口返回残缺（条数不符 / 维度不符 / 空数组 / 空输入 / `text_type` 非法）。

    危害口径（依 4.4、8.15）：HTTP 200 + 空向量会让稠密通道变成零命中却报告成功，
    混合检索静默退化成 BM25-only，而阈值是按相似度标定的——拒答判定从此悄悄失真。
    所以抛出即终止建索引，宁可失败也不交半成品（依 4.12）。
    """


class RerankResponseError(RuntimeError):
    """重排接口返回残缺（条数与请求不符 / 分数越界 / 超时限流后拿不到完整结果）。

    与上一个类的分工（依 4.14）：重排失败是**可回退**的——按规范 4.3 打印一行
    `[重排未生效: <原因>]` 后照融合顺序返回最终 k 条，回退不是异常路径；
    本类承载的是「响应本身残缺到不能信任」这一事实，供调用方决定是回退还是终止。
    尺子隔离另见 4.6：`rerank_score` 永不参与闸门比较。
    """
