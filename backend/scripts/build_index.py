"""构建检索索引（阶段二实现，当前为占位）。

阶段一不产出任何索引：卡片与事实条目落在 SQLite，检索层在阶段二基于 bge-m3 +
BM25 建立混合索引。本文件先占位，保证 `plan.md` 阶段一 Files 清单里的入口存在，
避免阶段二开工时再回头补目录结构。

约定（阶段二照此实现）：
- 索引必须可重建、带语料指纹；语料变更即重建，不做增量修补。
- 索引文件落 `Config.data_dir / "index"`，路径不得硬编码相对路径
  （阶段零已有过「从仓库根启动时相对路径踩空」的事故）。
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="构建检索索引（阶段二实现）")
    parser.add_argument("--rebuild", action="store_true", help="全量重建（阶段二用）")
    parser.parse_args(argv)
    print("检索索引构建：阶段二实现，本轮未接入。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
