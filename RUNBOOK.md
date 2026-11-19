# RedTrace RUNBOOK

## 阶段零F 能演示什么（2026-11-13）

**演示的是版式与信息层级，不是问答能力。** 本阶段交付的前端壳包含：

1. 七页骨架全部可路由：`/ask`（问答）、`/cards`、`/timeline`、`/map`、`/routes`、`/lesson-pack`、`/audit`；六页显示「将在阶段五/六/七接入」的最终形态线框说明，不含任何假图表。
2. 问答页版式演示（mock 契约样例）：正常回答（句末可聚焦上标引用编号 → 点击滚动定位出处卡并闪烁）、冲突并列（两张等权记载卡，恒 source_id 升序）、拒答区（深蓝灰中性系说明体，非报错红色，附最近邻参考卡）。
3. 出处卡两套版式：电子书（书名+出版社+出版年份+页码/章节）与文章（标题+发布机构+发布日期+链接）；定位缺失显示「定位待补」，字段缺失显示「××不详」。
4. 契约类型链：`src/api/types.ts` 由 `openapi-typescript` 从后端 OpenAPI 契约生成；后端字段改名会在**编译期**打断前端（`tests/contract.test.ts` 演练证明）。

**演示时必须口头声明：「数据为契约样例，真实回答在阶段三接入。」** 页面顶部 mock 横幅常驻同一句话。壳阶段没有检索、没有生成、没有假回答——这不是功能缺失，是阶段纪律（plan.md 阶段零F「不许出现任何看起来像功能的假实现」）。

## 环境

- 本机无全局 pnpm。用 bundled runtime（registry 已配 npmmirror，见 `frontend/.npmrc`；**该配置为仓库级，CI/外部协作者可用 `--registry` 或环境变量覆盖**，N-8）：

```powershell
$NODE = "C:\Users\HP\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"
$PNPM = "C:\Users\HP\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\pnpm\bin\pnpm.mjs"
# 等价于 pnpm <子命令>：
& $NODE $PNPM --dir frontend <子命令>
```

- Node v24（bundled）或 PATH 上的 `D:\NodeJS\node.exe` 均可；`playwright.config.ts` 支持环境变量 `DSH_PNPM_CLI` 覆盖 pnpm 路径。

## 常用命令（在 `frontend/` 下）

| 命令 | 作用 |
|---|---|
| `pnpm dev` | 开发服务器（`/api` 代理到 127.0.0.1:8000） |
| `pnpm build` | vue-tsc 全量类型检查 + Vite 生产构建 |
| `pnpm typecheck` | 仅类型检查（契约漂移的最终落点） |
| `pnpm test` | vitest 组件/契约/Token 套件（jsdom） |
| `pnpm exec playwright test` | e2e 视觉红线（C1/C3/B5/A2/A6，3 视口；需先 `playwright install chromium`，镜像见下） |
| `pnpm gen:api` | 从 `../backend/openapi.json` 重新生成 `src/api/types.ts` |

Playwright 浏览器下载（校园网/国内镜像）：

```powershell
$env:PLAYWRIGHT_DOWNLOAD_HOST = "https://cdn.npmmirror.com/binaries/playwright"
& $NODE $PNPM exec playwright install chromium
```

注：e2e 预览端口用 **8973**——4173 落在本机 Windows 系统保留段（`netsh interface ipv4 show excludedportrange protocol=tcp` 实测 4097–4196 被占），换机若再遇 `EACCES` 先查此表。

## mock / 真接口切换（VITE_USE_MOCK）

- `VITE_USE_MOCK=1`：问答页吃 `src/api/mock/`（契约类型实例化的登记表样例 5 行 + 三个版式场景）。
- `VITE_USE_MOCK=0`：走 `POST /api/ask` 真接口。**切 `=0` 之前必须先起后端**，且 `/api/ask` 目前是 501 占位（阶段三实现流水线），壳阶段切 `=0` 只能验证联调通路（`/api/health`），不应期望得到答案。

```powershell
# 1) 先导出契约（生成物 backend/openapi.json，已 gitignore，本地生成）
python backend/scripts/export_openapi.py

# 2) 重新生成前端类型并验证链条
cd frontend; pnpm gen:api; pnpm typecheck

# 3) 起后端（另一个终端）
python -m uvicorn app.main:app --app-dir backend --port 8000

# 4) 以真实接口模式构建/预览前端
$env:VITE_USE_MOCK = "0"; pnpm build; pnpm preview --host 127.0.0.1 --port 8973
```

**每个阶段末必须用 `VITE_USE_MOCK=0` 跑一次**（plan 阶段零F 接口约定）；任何一页仍在读 mock 视为未完成。

## 测试与门禁（关阶段条件）

```powershell
cd frontend
pnpm test        # vitest：契约漂移 4 项 + 组件红线 + token 复算（118 项，2026-11-13 终态）
pnpm typecheck   # vue-tsc 全量
pnpm build       # 生产构建
pnpm exec playwright test   # e2e 红线（19 例执行 × desktop/768/375 三视口；I-7 注入例在窄屏按设计 skip）
```

契约漂移演示（答辩可用）：临时把 `backend/app/qa/schemas.py` 里 `SourceOut.publisher` 改名 → `export_openapi.py` + `pnpm gen:api` + `pnpm typecheck` → 编译期报错（`tests/contract.test.ts` 每次自动演练并恢复现场）。

## 目录速览

- `src/api/types.ts` —— **生成物，永不手写、永不改**（头部有 openapi-typescript 标记，测试真读文件校验）。
- `src/api/adapter.ts` —— 后端蛇形字段名唯一消费层；接真接口/契约变更只改这里（组件与测试不烧）。
- `src/api/model.ts` —— 前端 props 模型（camelCase）。
- `src/components/` —— SourceCard / ConflictPair / CitationMark / RefusalNotice（+PhaseEmptyState）。
- `src/styles/tokens.css` —— 设计 token 唯一色值来源；组件内禁止硬编码色值（扫描测试覆盖 src+public+index.html 全检测面）。
- `tests/` —— vitest 套件与 fixtures；`tests/e2e/` —— Playwright 红线；`tests/lib/css-audit.ts` —— 与 visual-qa 变异样本回归共用的实现。

## 阶段二 检索层（2026-11-18/19）

**试点边界（演示前必须声明）**：本阶段所有数字来自 20 单元 / 125 卡 / 223 条目的试点语料
（9 部核心电子书无本地原件），不是全量语料的结果。卡片数已达阶段一退出线 120，但条目 223/400、
可解析单元 11/50 未达标；全量数字需补采原件后经用户再次授权重跑。阈值可分性「重叠」未达标，
API 重排已于 2026-11-19 账户充值后补跑真实冒烟并修复请求体形态缺陷（报告「真实 API 重排冒烟」节），
5 文档 0.81–0.88 s、分数 0.24–0.84、尺子隔离成立——但阈值可分性「重叠」仍未达标，且重排分
永不参与闸门。两项边界均已在 `docs/评测报告.md` 如实记录，不得以试点数字冒充全量验收。

### 常用命令（在 `backend/` 下；`cd backend` 必须，仓库根直跑会 ModuleNotFoundError）

```powershell
cd backend

# 1) 建索引（api 档走 Config 的 EMBEDDING_BACKEND；--rebuild 强制全量重建）
python scripts/build_index.py --rebuild
# 无 key / 离线演练：不下载任何权重，退化为 BM25-only，产物不得用于达标判定
python scripts/build_index.py --embedding-backend stub --rebuild

# 2) 三指标评测（只跑检索，零 token 成本）
python scripts/eval_retrieval.py
python scripts/eval_retrieval.py --minimal        # 含摊薄对照（迷你库）
python scripts/eval_retrieval.py --rrf 20          # 融合常数扫档

# 3) 拒答阈值标定（扫 0.40–0.60，写 data/index/threshold.json）
python scripts/eval_retrieval.py --calibrate

# 4) 切块扫档（merged 档需单独索引目录；定稿 single）
python scripts/build_index.py --out data/index-merged --block-mode merged --rebuild
python scripts/eval_retrieval.py --out data/index-merged --block-mode merged

# 5) 门禁
python -m ruff check .
python -m pytest -q        # 558 passed（2026-11-19）
```

`build_index.py` 自检会打印六件事：条目/向量/倒排是否一致、两条通道各自命中数、实际生效的
embedding 配置（不是 `.env` 写了什么）、重排档可用性、空检索串计数、两个指纹与阈值标定条件。
任一侧声明可用却零命中 → 退出码 2，不落半套索引（stub 档稠密为 0 属合法降级，不算故障）。

### 三档切换与降级日志

| 维度 | 档位 | 切换方式 | 行为 |
|---|---|---|---|
| 向量 | `api` / `local` / `stub` | `EMBEDDING_BACKEND` 或 `--embedding-backend` | `api` 走云端 `/embeddings`；`local` 需先 `pip install -e ".[retrieval]"` 并手动取权重；`stub` 无向量、BM25-only |
| 重排 | `api` / `local_lexical` / `off` | `RERANK_BACKEND` 或 `--rerank-backend` | `api` 走云端 `/reranks`（已实测可用：扁平 `query`/`documents` 请求体，5 文档约 0.8s）；`local_lexical` 本地词面重排；`off` 不重排 |

**绝不自动换档**：配置缺 key、依赖或权重时一律显式报错并点名补齐路径，不会静默退回其它档
（规范 4.13）。降级是默认行为而非异常路径：重排跑不了时按融合顺序返回，并打一行
`重排未生效: <原因>`。库内用 `logger.warning("重排未生效: %s", reason)`，默认不输出到终端：
需要看到这行时，在调用方（CLI / 装配层）配置 logging，例如：

```python
import logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
```

或在 `backend/.env` / 运行命令里把日志级别调到 WARNING（具体装配点见阶段三接入时的 `app/main.py`）。
`build_index.py` 的自检行 `重排档=...` 会直接打印到 stdout，无需配日志即可判断这一档是否生效。

### 索引过期与阈值过期

- 索引双指纹：**语料指纹**（卡片/条目变更即变）+ **向量配置签名**（模型 + 维度 + 基址哈希 +
  `text_type` 两侧组合，任一变更即变）。`ensure_ready()` 比对不一致时抛 `IndexStaleError` /
  `IndexNotBuiltError`，CLI 提示重建：`python scripts/build_index.py --rebuild`。
- 阈值文件 `data/index/threshold.json` 自带标定条件（语料指纹、向量签名、rrf 常数、
  稠密/稀疏 top、block_mode、top_k、生成时间）。换索引或换配置后 `calibrated_threshold()` 抛
  `ThresholdStaleError` → 必须重跑 `python scripts/eval_retrieval.py --calibrate`，不得沿用旧 tau。
- 重排分永不参与闸门：`Hit.score` 是唯一跨请求可比的相似度尺子，`Hit.rerank_score` 只参与排序；
  无分数是 `None`（不是 -1 或 0.0），`0.0` 是合法低分（R12）。

### 阶段一抽取路径的两条现行口径（T1.5 修复后）

1. `--dry-run` 现在**零 LLM 调用**：旧实现 dry-run 仍全额调抽取模型（20 分钟无输出），修复后
   同命令降到 0.37s；dry-run 返回的是解析/切块结果，不是抽取结果。
2. 换供应商时必须逐项确认 `enable_thinking` 参数：供应商缺省开推理会让请求 140.5s 撞超时；
   显式携带该字段后 9.8s（`LLM_TIMEOUT_S=300` 保持模块常量，R21）。这不是可移植默认值，
   换模型/换网关须重测并在决策记录 007 第五节留痕。

复现与数字口径见 `docs/评测报告.md`；阶段二裁决与进度台账见 `.superpowers/sdd/plan/progress.md`
（工作区临时文件，长期留档需用户同意）。

## 阶段三 可溯源问答（2026-11-19）

**演示前声明**：问答流水线已接真检索 + 真 LLM + 三层引用校验，但阈值 τ=0.41 在试点语料上
「可分性重叠」（阶段二已记录），部分可答题会被分数闸门误拒；冲突组本阶段恒空（阶段四接）。
全量数字待补采 9 部电子书后重跑。

### 命令（在 `backend/` 下）

```powershell
cd backend

# 起服务（问答页走真接口）
python -m uvicorn app.main:app --app-dir . --port 8000

# 一条问答（需已建索引 + 阈值文件；旧库会自动补 V2 审计列）
curl -X POST http://127.0.0.1:8000/api/ask -H "Content-Type: application/json" `
  -d '{"question":"红军长征何时开始？"}'

# 门禁
python -m ruff check .
python -m pytest -q          # 607 passed（2026-11-19）
```

前端：`pnpm test`（117）/ `pnpm build` / `pnpm exec playwright test`（19 passed + 2 skipped）。
问答页生产入口已**无 mock 分支**；`src/api/mock/` 的契约样例只供组件与 e2e 测试夹具使用。

### 流水线与关键口径

1. 顺序：检索（`LocalBackend`，默认路径必走）→ 证据组装（按 claim_id 回表取条目+来源+定位）
   → 拒答闸门（空证据/低分**不调模型**）→ 受约束生成（temperature=0、`enable_thinking` 显式）
   → 三层引用校验（编号 / 引文逐字 / 主体一致含别名）→ 出处回链 + qa_logs/audit_logs。
2. **闸门只认 `Hit.score`**（跨请求可比的相似度），重排分永不参与；三原因码
   `not_covered` / `no_evidence` / `all_claims_rejected`，响应带 `retrieved_count` / `top_score` /
   `threshold` / `gate_note` 四个审计字段，前端拒答区展示可解释说明行。
3. **逐字定位读 parsed 的 `full_text`**（不是 blocks 拼接——块边界会切断引文），且原文字典的键是
   **claim_id** 而非引用序号 `[n]`（真实 claim_id 可达三位数，用引用号查会全查不到 → 真模型答案
   被全剔除）。这两处是真实 LLM 冒烟暴露并修复的缺口（2026-11-19）。
4. 旧库升级：试点库是阶段一建的 V1，`answer_question` 写日志前会幂等跑 V2 迁移补四审计列。
5. 结构化语料放宽：罕见实体词逐字命中 + 只出现在 ≤30% 候选 + 表格式行（≥3 字段且 ≥60% 含数字）
   三条同时成立才降到 `term_floor=0.33`；设 0 即关闭。

### 双实现与降级

| 维度 | 档位 | 切换 | 行为 |
|---|---|---|---|
| 生成 | `online` / `local` | `LLM_BACKEND` | online 走 `chat/completions`（复用阶段一 `llm_*` 配置）；local 需 `llama-cpp-python` + 自取 GGUF，缺依赖显式报错不换档 |

提示词版本 `PROMPT_VERSION` 写进 qa_logs.prompt_version；改 `prompt.py` 必须递增版本。
