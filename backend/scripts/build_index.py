"""构建检索索引（阶段二 T3 实现）。

约定（阶段一占位时已定，沿用）：
- 索引必须可重建、带语料指纹；语料变更即重建，不做增量修补。
- 索引文件落 `Config.data_dir / "index"`，路径不得硬编码相对路径
  （阶段零已有过「从仓库根启动时相对路径踩空」的事故；task-8 又修过入库侧同形缺陷，
  所以这里与 `app/ingestion/cli.py` 用同一口径：不传 `--out`/`--db` 时回落 `Config.data_dir`）。

自检输出按 `refimpl-notes.md` 第 6 项（doctor 六件事）：条目/向量/倒排是否一致、两条通道
各自的命中数、实际生效的 embedding 配置（不是 `.env` 写了什么）、重排档可用性、空检索串计数、
两个指纹与阈值文件标定条件是否匹配。

为什么这些必须打印而不是只写日志：计划步骤 3b 的事故形态是「某条通道空转却报告成功」，
日志里的 `Got 0 from docstore` 长期无人注意（004 §三-1）。打印到 stdout 的东西才是
人真的会看的东西。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# 直接 `python scripts/build_index.py` 时 sys.path[0] 是 scripts/，`app` 包看不见。
# 与 `scripts/export_openapi.py` 同一处理方式（本仓既有约定），不靠 PYTHONPATH 环境变量。
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Config, get_config
from app.db.migrate import default_db_path
from app.retrieval.errors import EmbeddingResponseError
from app.retrieval.local import META_FILENAME, LocalBackend, default_index_dir

THRESHOLD_FILENAME = "threshold.json"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="构建检索索引（阶段二：稠密向量落 SQLite + BM25/jieba 稀疏）"
    )
    parser.add_argument("--db", help="SQLite 主库路径（默认 Config.data_dir/redtrace.db）")
    parser.add_argument("--out", help="索引目录（默认 Config.data_dir/index）")
    parser.add_argument("--aliases", help="别名表路径（默认 data/aliases.yml），决定 jieba 用户词典")
    parser.add_argument(
        "--embedding-backend",
        choices=["api", "local", "stub"],
        help="向量档，显式选档（默认取 EMBEDDING_BACKEND 配置）。stub = 无向量、退化为 BM25-only",
    )
    parser.add_argument(
        "--block-mode",
        choices=["single", "merged"],
        default="single",
        help="切块粒度档：single=单条目成块；merged=同卡片多条目合并（上限 512 token）",
    )
    parser.add_argument(
        "--min-search-text-chars",
        type=int,
        default=None,
        help="检索串最小字符数，短于此的块被拦下（默认 10，见 task0-report 6.4-3）",
    )
    parser.add_argument("--rebuild", action="store_true", help="强制全量重建；不带则复用现有索引")
    return parser


def _describe_embedding(config: Config) -> str:
    """实际生效的 embedding 配置（不是 `.env` 写了什么——两者会在漏传 text_type 时分叉）。"""
    return (
        f"生效配置：档={config.embedding_backend} 模型={config.embedding_model or '<未声明>'} "
        f"维度={config.embedding_dim} batch={config.embedding_batch_size} "
        f"text_type={config.embedding_text_type_document or '<未声明>'}"
        f"/{config.embedding_text_type_query or '<未声明>'}"
    )


def _threshold_note(index_dir: Path) -> str:
    """阈值文件状态（D12：`data/index/threshold.json` 由 T5 标定，本阶段必然缺失）。"""
    path = index_dir / THRESHOLD_FILENAME
    if not path.is_file():
        return "阈值文件：待 T5 标定（本阶段不产出阈值，拒答判定尚未启用）"
    return f"阈值文件：已存在 {path}（T5 标定产物，指纹比对见 calibrate 命令）"


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    config = get_config()
    if args.embedding_backend:
        config = config.model_copy(update={"embedding_backend": args.embedding_backend})

    db_path = Path(args.db) if args.db else default_db_path()
    index_dir = Path(args.out) if args.out else default_index_dir(config)
    aliases_path = Path(args.aliases) if args.aliases else None
    min_chars = args.min_search_text_chars

    print(f"索引构建：db={db_path} out={index_dir} block_mode={args.block_mode}")
    if config.embedding_backend == "stub":
        print("向量档=stub：本轮产物不得用于达标判定（无稠密向量，检索退化为 BM25-only）")
    print(_describe_embedding(config))

    kwargs: dict[str, object] = {
        "config": config,
        "db_path": db_path,
        "index_dir": index_dir,
        "block_mode": args.block_mode,
    }
    if aliases_path is not None:
        kwargs["aliases_path"] = aliases_path
    if min_chars is not None:
        kwargs["min_search_text_chars"] = min_chars

    started = time.monotonic()
    backend = LocalBackend(**kwargs)  # type: ignore[arg-type]

    if not args.rebuild and (index_dir / META_FILENAME).is_file():
        try:
            backend.ensure_ready()
        except Exception as exc:  # noqa: BLE001 - 过期/损坏都属同族，统一转成"须重建"
            print(f"现有索引不可复用：{exc}")
            print("请按提示重建：`python scripts/build_index.py --rebuild`")
            return 2
        print("复用现有索引（未带 --rebuild）：指纹与当前语料、当前向量配置一致")
        report = backend.build_report
        print(f"条目数={backend.doc_count}")
        _print_channel_stats(backend, index_dir)
        print(f"耗时 {int((time.monotonic() - started) * 1000)} ms")
        if report.block_mode:
            print(f"切块档={report.block_mode}")
        return 0

    if not args.rebuild and not (index_dir / META_FILENAME).is_file():
        print("未发现现有索引：开始首次构建（如需强制重建请加 --rebuild）")

    try:
        report = backend.index(force=True)
    except EmbeddingResponseError as exc:
        # 步骤 3b 的同族事故：声明稠密可用却拿不到向量。非零退出，不落半套索引。
        print(f"稠密通道未生效：{exc}")
        print("已中止构建，未写入任何索引文件（依 4.12：宁可失败也不交半成品）")
        return 2
    except ValueError as exc:
        print(f"索引构建失败：{exc}")
        return 2

    # ① 条目 / 向量 / 倒排三者一致性
    print(
        f"条目数={report.docs} 向量数={report.vectors} 倒排词条数={report.postings} "
        f"库内条目={report.claims_in_db}"
    )
    print(f"空检索串条目：{report.empty_search_texts} 条")
    if report.skipped_short:
        print(f"过短被拦：{report.skipped_short} 条（阈值 {report.min_search_text_chars} 字符）")
    # ② 两条通道各自的命中数
    stats = _print_channel_stats(backend, index_dir)
    # ③ 两个指纹
    print(f"语料指纹 {report.corpus_fingerprint}")
    signature = report.vector_signature or {}
    print(f"向量配置签名 {signature.get('digest', '<未写>')}（{signature}）")
    # ④ 重排档可用性（T4 才接入，现在照实说没接入）
    print(f"重排档=未接入（T4 接入后此处显示 api/local_lexical/off 实际状态）：{backend.rerank_note()}")
    # ⑤⑥ 阈值文件与切块档
    print(_threshold_note(index_dir))
    print(f"切块档={report.block_mode} 最小检索串长度={report.min_search_text_chars}")
    print(f"耗时 {report.elapsed_ms} ms")

    dead = _dead_channels(stats, report)
    if dead:
        print(f"通道未生效：{'、'.join(dead)}（步骤 3b：任一侧长期为 0 判未生效，不得报告构建成功）")
        return 2
    return 0


def _print_channel_stats(backend: LocalBackend, index_dir: Path) -> object:
    stats = backend.index_stats()
    print(
        f"稠密 {stats.dense_hits} 条 / 稀疏 {stats.sparse_hits} 条"
        f"（自检探针：{backend.probe_query}）"
    )
    print(f"索引文件：{index_dir}")
    return stats


def _dead_channels(stats: object, report: object) -> list[str]:
    """判「通道未生效」：声明可用却零命中（stub 档的稠密 0 是合法降级，不算故障）。"""
    dead: list[str] = []
    dense_hits = getattr(stats, "dense_hits", 0)
    sparse_hits = getattr(stats, "sparse_hits", 0)
    dense_available = getattr(report, "dense_available", False)
    if dense_available and not dense_hits:
        dead.append("稠密通道")
    if not sparse_hits:
        dead.append("稀疏通道")
    return dead


if __name__ == "__main__":
    sys.exit(main())
