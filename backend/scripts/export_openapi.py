"""把 OpenAPI 契约导出为 JSON（阶段零F 步骤 2）。

用法：`python scripts/export_openapi.py [--out <path>]`，默认写 `backend/openapi.json`
（生成物，已在 .gitignore 中）。

关键约束——**不起服务、不读环境变量、不联网**：纯导入 `app.main` 就能导出，前端
`pnpm gen:api` 依赖这一点（本地没有 .env、后端没启动时也必须能生成类型）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DEFAULT_OUT = BACKEND_ROOT / "openapi.json"


def export_openapi(out: Path) -> Path:
    """导出契约 JSON：UTF-8、不转义中文、带尾换行，返回写入路径。"""
    from app.main import app

    spec = app.openapi()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(description="导出 RedTrace 后端 OpenAPI 契约")
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help="输出路径（默认 backend/openapi.json）",
    )
    args = parser.parse_args(argv)
    out = export_openapi(args.out)
    print(f"已导出 OpenAPI 契约：{out}")
    return out


if __name__ == "__main__":
    main()
