# `backend/data/` 数据来源文件说明

本目录的数据类文件有两份，职责不同：

| 文件 | 作用 | 谁维护 |
|---|---|---|
| `来源登记表.csv` | 每个语料单元（电子书 1 部 / 文章 1 篇）登记一行，是入库的准入闸门 | 采编人员随取随登 |
| `来源白名单.yml` | 权威来源准入名单（机构全称 + 域名 + 别名 + 核验记录） | 阶段零步骤 5 定稿，增补须登记 |

两份文件都由 `app/ingestion/registry.py` 的 `load_registry()` 读取校验；不合格的行直接抛 `ValueError`，不会静默放过。

## 一、`来源登记表.csv` 各列填法

表头九列固定如下，顺序可调、列名不可改（UTF-8 编码，用 Excel 另存时选「CSV UTF-8」即可，读取端兼容 BOM）：

| 列名 | 含义 | 必填 | 怎么填 |
|---|---|---|---|
| `source_id` | 来源编号 | 是，且全表唯一 | `S001`、`S002`…… 递升，不复用、不跳号 |
| `title` | 来源名称 | 是 | 电子书填书名（含卷次），文章填原文标题 |
| `publisher` | 发布者 | 是（电子书必填出版社） | 电子书填**出版社全称**，文章填**发布机构全称**，须能在白名单 `name`/`aliases` 命中 |
| `publish_date` | 出版年 / 发布日期 | 是，不得留空 | 电子书必须是落在 **1840–2100** 的四位年份（`1985`、`1985年`、`1985年10月`、`1985-10`、`1985.10.05` 均可；`19850`、`198510`、`公元前1985`、`年代不详1985` 一律拒绝）；文章填发布日期 `YYYY-MM-DD`，确实查不到填字面值 `年代不详` |
| `url_or_path` | 链接或文件路径 | 是 | 电子书填 `data/raw/` 下的相对路径；文章填原链接，并同时保存 HTML/PDF 快照 |
| `access_date` | 获取日期 | 是 | `YYYY-MM-DD`，防链接失效后无法核验 |
| `license_note` | 授权或公开获取说明 | 是 | 至少写 `公开出版物` 或 `官网公开文章`，或写具体口径（如「原载《中国档案报》总第 XXX 期第 X 版」） |
| `corpus_tier` | 语料层级 | 是 | 只允许 `核心` 或 `补充` |
| `media_type` | 载体类型 | 是 | 只允许 `电子书` 或 `文章` |

### 校验规则（与 `registry.py` 一致）

1. `source_id` 全表唯一，重复即报错；
2. `title`、`url_or_path`、`access_date` 非空；
3. `publish_date` 非空，允许字面值 `年代不详`；
4. `corpus_tier` ∈ {`核心`, `补充`}；
5. `media_type` ∈ {`电子书`, `文章`}；
6. `电子书` 必须有 `publisher`，且 `publish_date` 是落在 1840–2100 的四位年份（不得为 `年代不详` 或混写）；
7. `publisher` 归一后必须在 `来源白名单.yml` 内，否则报错（信息含 `whitelist`）；
8. `license_note` 非空；
9. 命中的白名单条目必须 `verified: true` 才算有效准入——`false`、字段缺失、非布尔值（`"true"` / `1` / `"yes"`）一律拒绝；未核验条目的**别名同样被拒**，防止换个写法绕过。错误信息同时含 `whitelist` 与 `verified`，并给出机构名、`verified_at` 与「待核验，补核后改 true」；机构根本不在名单里时只报「不在 whitelist」，两种情况可区分。

> 准入只看 `verified` 与名称/别名命中：白名单条目的 `domain` 与 `sections` **不参与判定**（空 `domain` 是合法状态，理由见第二节），登记一行时不要因为 yml 里 `domain: ""` 就以为会被拦下。

报错信息形如 `第 12 行（S011）：电子书的 publish_date 必须含四位年份…`，带行号与编号，便于直接定位。

## 二、`来源白名单.yml` 的读取契约

`registry.py` 按下列形态解析（两种都支持，采编时保持其一即可）：

```yaml
# 形态 A：顶层直接是机构列表（当前文件采用）
- name: 中央党史和文献研究院
  aliases:
    - 中共中央党史和文献研究院

# 形态 B：顶层是映射，机构列表挂在某个键下
institutions:
  - name: 人民出版社
    aliases: [人民版社]
```

- 顶层为映射时，识别的列表键：`institutions` / `whitelist` / `sources` / `publishers` / `organizations` / `机构` / `名单`；若都没有，则把映射的键名当作机构名。
- 每个条目取 `name`（或 `机构` / `全称` / `发布者` / `publisher` / `title`）与 `aliases`（或 `别名` / `简称`）参与名称比对；`verified` 决定是否算有效准入（规则 9）；`note`、`verify_source` 只作留档。
- **`domain` 与 `sections` 不参与准入判定，准入只看 `verified` 与名称/别名命中。** `domain: ""` 是合法状态——多数出版社没有可直连的独立官网，准入依据是写在 `verify_source` 的官方通报页；`sections: []` 表示「栏目未实测」，是给采集人员的提示，不是准入条件。看到空 `domain` 不要以为该行会被拦下。
- 机构名归一方式：全角转半角（NFKC）→ 去掉全部空白 → 去掉首尾句点（半角 `.` 与中文句号 `。` 都去，NFKC 不映射 U+3002）。因此 `人民日报 （社）` 与 `人民日报(社)` 视为同名，`某某出版社。` 也能命中 `某某出版社`。

### `verified` 闸门（lead 2026-11-13 裁决，已落地为规则 9）

白名单文件头部注释写明「`verified: false` 的条目一律不得入库」。这条承诺现已由代码执行：只有 `verified` 为布尔 `true` 的条目进入有效准入集合，`false`、字段缺失、非布尔值都归入未核验集合并拒绝入库。裁决前该闸门形同虚设（`人民出版社`、`中央文献出版社`、`新华出版社`、`中共党史网`、`本校官网` 五条 `verified: false` 均可通过），现已由 6 条测试覆盖，含「未核验条目的别名同样被拒」这一绕过路径。

## 三、常用调用方式

```python
from pathlib import Path
from app.ingestion.registry import load_registry

records = load_registry(Path("data/来源登记表.csv"))  # 白名单默认取 data/来源白名单.yml
```

批量入库与统计在阶段一的 `app/ingestion/cli.py` 中提供。

## 四、已知限制

1. **`app/main.py` 里没用 FastAPI 惯用的 `Depends` 默认参数。** 本机 ruff 0.17 的默认规则集包含 flake8-bugbear 的 `B008`（禁止在参数默认值里做函数调用），而 `def health(cfg: Config = Depends(get_config))` 正是这种写法，`ruff check .` 会直接报错。阶段零的处置是在处理函数体内调用 `get_config()`——每次请求重新读配置，行为与依赖注入等价。**阶段三的处置方案**：`api/` 下多个路由都要用 `Depends`，届时按标准做法对 `app/api/*` 豁免 `B008`（`[tool.ruff.lint.per-file-ignores]`），而不是继续绕开惯用法；该变更需一并写入决策记录。本阶段不动 `[tool.ruff]`，因为 brief 只批准了 `line-length` 与 `target-version` 两项配置。
2. **默认路径锚在 `backend/` 而非当前工作目录。** `Config.data_dir` 默认 `backend/data`，`env_file` 默认 `backend/.env`，都按 `app/core/config.py` 的位置取绝对路径。因此从仓库根启动 `uvicorn backend.app.main:app` 与从 `backend/` 启动行为一致；用 `DATA_DIR` 环境变量覆盖即可整体迁移数据目录（阶段一/二的语料与索引路径依赖这一点）。
