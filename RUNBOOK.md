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
