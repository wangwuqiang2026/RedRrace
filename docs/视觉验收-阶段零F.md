# 视觉验收 · 阶段零F 监管工作文档

> **文件职责**：visual-qa 在本阶段的过程与发现记录。**§1/§2 归 visual-qa 维护；§3 为 frontend-dev 人工勾选项预留区，由它追加，双方都用 `edit` 局部改、不整篇覆盖。**
> **口径来源**：`docs/设计规范.md`、`docs/视觉验收清单.md`（11 条红线 / 56 项）。
> **本轮状态（2026-11-13）**：V1-a、V1-b 已交付；tokens.css 与四组件实审未开始（产物未出）。

---

## 1. 红线可自动化性（V1-a）

判定口径：**完全可自动化** = 测试通过即红线通过；**大部分可自动化** = 结构性判据可断言，主观/语义残余部分需人工；**必须人工** = 无法写出可靠自动断言。工具约定：vitest + @vue/test-utils（组件级 DOM/props 断言）、Playwright（e2e + `getComputedStyle` 实测）、axe-core（无障碍规则子集）、python-docx（导出物解析）。

### 1.1 分类总表

| # | 红线 | 分类 | 主要工具 | 自动化覆盖的判据 | 残余人工动作（目测标准） |
|---|---|---|---|---|---|
| A1 | 颜色非唯一区分 | 大部分可自动化 | vitest + Playwright | 每个状态元素同含图标节点+文字节点；标记形状（菱形/圆形）可读 | 灰度打印/模拟灰度模式对照，确认信息仍完整（目测：无状态退化） |
| A2 | 史实句必带引用编号 | 混合（fixture 可自动，语义判定人工） | Playwright + 后端夹具 | 夹具答案每句末有可聚焦 `sup`；`aria-label` 指向存在卡片 | 真实长答案抽检"哪些句子算史实陈述"（目测：无裸史实句） |
| B1 | 出处卡信息完整 | 完全可自动化 | vitest 双载体夹具 | 六字段全部非空、缺值出"××不详"占位、字段顺序固定 | 无 |
| B5 | 拒答不像报错 | 大部分可自动化 | Playwright computed style + 文本扫描 | 底色=token `--paper-muted` 解析值、文字色= `--refusal-ink` 解析值、无 `role=alert`、图标名=`info`、禁用词零命中 | 版式气质目测：是否读起来像"说明"（对照 §5.1.4 线框） |
| B6 | 拒答不含猜测 | 必须人工为主 | 部分文本断言 | "仅参考，不构成对该问题的回答"整句存在；参考卡标题≠被问对象 | 拒答文案通读：无关于被问对象的事实句（哪怕带"可能"） |
| C1 | 冲突两卡等权 | 完全可自动化 | Playwright computed style 成对比较 | 两卡 6 项样式属性两两相等；禁用词（更可信/仅供参考）零命中；DOM 序=视觉序 | 目测复核一次即可 |
| C3 | 冲突纯编号序 | 完全可自动化 | Playwright + 打乱夹具 | 交换出版年份后重渲染，顺序不变、恒按 `source_id` 升序 | 无 |
| E2 | 未定位不画点 | 完全可自动化 | Playwright + 接口 mock | 无坐标条目不出现在 scatter series 数据；出现在未定位列表；说明行文案存在 | 无 |
| H2 | Word 页脚+出处表 | 完全可自动化 | python-docx（pytest） | 每页页脚固定句；出处表列名与列序；正文上标↔表内编号一一对应、无悬空 | 打印预览看表头灰度可读性 |
| I1 | 审核三色三通道 | 完全可自动化（结构）+人工灰度 | vitest + Playwright | 徽标含 ✓/✎/⊘ 图标节点+中文状态文字；`aria-label` 完整 | 灰度打印徽标可区分 |
| I5 | 审核台拒答非错误红 | 完全可自动化 | Playwright + stylelint/源码扫描 | 拒答徽标色=`#33526B` 系；`--error-red` 在审核台 DOM 零命中；`--error-red` 出现处同层必有重试按钮 | 无 |

**统计**：完全可自动化 6 条（B1/C1/C3/E2/H2/I5）；大部分可自动化 3 条（A1/B5/I1）；混合/必须人工为主 2 条（A2/B6）；I1 的灰度目测并入 A1 人工动作统一做。阶段八验收执行面 = 自动化套件（CI 常跑）+ 一次人工目测单（灰度打印 + 拒答/报错观感 + 长答案裸句抽检）。

### 1.2 断言写法（伪代码级）

> 记号：`tok(x)` = 取 CSS 变量 `--x` 的解析值；组件选择器以 `data-test` 属性锚定（阶段八契约测试已用该约定，plan 阶段八步骤 1）。

**A1 · 颜色非唯一区分（vitest 组件级 + ECharts 输出）**
```js
// 状态徽标组件：三通道断言
for (const s of ["通过", "需修改", "拒答", "存疑", "待考", "未收录"]) {
  const w = mount(Badge, { props: { status: s } });
  expect(w.text()).toContain(s);                 // 文字通道
  expect(w.find("svg").exists()).toBe(true);     // 图标通道
  expect(w.attributes("style")).toBeTruthy();    // 颜色通道（样式走 token）
}
// 图表侧（Playwright）：存疑节点 label 前缀文字必须存在，形状可读
await expect(page.locator('[data-test=timeline]')).toContainText("[存疑]");
```
人工残余：`page.emulateMedia({ media: 'print' })` 截图 → 灰度图对照清单 A1。

**A2 · 史实句引用编号（Playwright，夹具驱动 + 人工抽检）**
```js
// 夹具：fixture ask 答案 3 句、每句绑定编号 [1][2][3]
for (const p of await page.locator(".answer p").all()) {
  const sups = await p.locator("sup a[data-test=cite-ref]").count();
  expect(sups).toBe(fixture.expectedCiteCount(idx)); // 句↔编号数由夹具声明
  // 每个编号锚点必须指向存在的卡片
  for (const ref of await p.locator("sup a").evaluateAll(as => as.map(a => a.getAttribute("href"))))
    expect(await page.locator(ref).count()).toBe(1);
}
```
人工残余：真实长答案随机抽 10 条读——"有没有一句史实没挂编号"。

**B1 · 出处卡完整（vitest 双载体夹具）**
```js
const ebook = mount(SourceCard, { props: { src: fixtures.ebook } });
expect(order(ebook)).toEqual(["徽标:电子书","标题","出版社","出版年份","页码或章节","引文","回链"]);
expect(ebook.text()).not.toMatch(/出版社[：:]\s*(·|$)/);   // 无空字段
const art = mount(SourceCard, { props: { src: fixtures.ebook_no_date } });
expect(art.text()).toContain("出版年份不详");              // 缺值走占位
```

**B5 · 拒答不像报错（Playwright）**
```js
const zone = page.locator('[data-test=refusal]');
expect(await zone.evaluate(e => getComputedStyle(e).backgroundColor)).toBe(tok("paper-muted"));
expect(await zone.locator("p").first().evaluate(e => getComputedStyle(e).color)).toBe(tok("refusal-ink"));
await expect(zone.locator('[role=alert]')).toHaveCount(0);
await expect(zone.locator("svg[data-icon=alert-triangle], svg[data-icon=x-circle]")).toHaveCount(0);
expect(await zone.innerText()).not.toMatch(/错误|失败|异常|无法处理|出错/);
```

**B6 · 拒答不含猜测（文本断言 + 人工）**
```js
expect(await zone.innerText()).toContain("仅参考，不构成对该问题的回答");
for (const card of suggestions) expect(card.title).not.toBe(askedPersonName); // 参考≠被问对象
// 无法自动：语义级"这算不算对该人物陈述事实"——列入人工目测单
```

**C1 · 等权成对比较（Playwright，最硬的一条自动化）**
```js
const [k1, k2] = await page.locator('[data-test=conflict] .source-card').all();
for (const prop of ["fontSize","fontWeight","backgroundColor","borderColor","padding","width"]) {
  const a = await k1.evaluate((e,p)=>getComputedStyle(e)[p], prop);
  const b = await k2.evaluate((e,p)=>getComputedStyle(e)[p], prop);
  expect(a).toBe(b);                        // 6 项属性两两相等，任一不等即红线不通过
}
const txt = await page.locator('[data-test=conflict]').innerText();
expect(txt).not.toMatch(/更可信|推荐|较新来源|仅供参考/);   // 禁用词扫描
expect(txt).toContain("记载一"); expect(txt).toContain("记载二");
```

**C3 · 纯编号序（Playwright + 打乱夹具）**
```js
const ids = ["S031","S012","S007"];                       // 故意与出版年逆序
await page.goto(`/ask?fixture=conflict_shuffle&ids=${ids}`);
const domOrder = await page.locator('[data-test=conflict] [data-source-id]').evaluateAll(es => es.map(e => e.dataset.sourceId));
expect(domOrder).toEqual([...domOrder].sort());           // 恒 source_id 升序
// 附加：视觉序=DOM 序（getBoundingClientRect().top/left 单调一致）
```

**E2 · 未定位不画点（Playwright mock 接口）**
```js
await page.route("**/api/map**", r => r.fulfill({ json: { points: [...], unresolved: [{name:"×旧址"}] } }));
const seriesData = await page.evaluate(() => window.__chart.getOption().series[0].data.map(d => d.name));
expect(seriesData.join()).not.toContain("×旧址");          // 地图零猜测点位
await expect(page.locator('[data-test=unresolved]')).toContainText("×旧址");
await expect(page.locator('[data-test=unresolved]')).toContainText("不在地图上标注");
```

**H2 · Word 导出（pytest + python-docx）**
```python
doc = Document(export_path)
for sec in doc.sections:
    assert "资料来源：RedTrace 卡片库，见文末出处表" in sec.footer.paragraphs[0].text
cols = [c.text for c in table(doc, "出处").rows[0].cells]
assert cols == ["编号","书名/标题","出版社/发布机构","出版年份/发布日期","页码·章节/链接"]
sup_ids = extract_superscripts(doc)                       # 正文上标集合
assert set(sup_ids) <= {r[0].text for r in table_rows(doc)} and len(sup_ids) == len(set(sup_ids))  # 无悬空编号
```

**I1 · 三色三通道（vitest，同 A1 徽标断言，逐状态扩图标名）**
```js
expect(w.find('[data-icon=check]').exists()).toBe(status === "通过");
expect(w.find('[data-icon=pencil]').exists()).toBe(status === "需修改");
expect(w.find('[data-icon=ban]').exists()).toBe(status === "拒答");
```

**I5 · 拒答态无错误红（Playwright + 源码白名单扫描）**
```js
const badge = page.locator('[data-test=audit-verdict][data-status=refused]');
expect(colorToHex(await badge.evaluate(e=>getComputedStyle(e).color))).toBe(tok("refusal-ink"));
expect(colorToHex(await badge.evaluate(e=>getComputedStyle(e).color))).not.toBe(tok("error-red"));
await expect(page.locator('[data-test=audit-page] *:has-text("错误")')).toHaveCount(0); // 审核台故障词零命中
```
```bash
# 源码级静态扫描（grep 即可，无需框架）：--error-red 出现处 3 行窗口内必须含重试按钮
rg -n --error-red frontend/src -A3 -B3 | awk '/error-red/ && !/retry|重试/{print "违规:"$0; exit 1}'
```

---

## 2. Token 一致性预核对（V1-b）

**方法**：用独立脚本（不引用规范生成物）按 WCAG 相对亮度公式对 `docs/设计规范.md` 全部色值重算：①§3.4 表 21 行逐行复算比对；②扫描正文各处引用/使用场景，找出**表外但被正文依赖**的搭配补算；③通读核对 token 色值前后一致性与文字性断言。

### 2.1 结果一：§3.4 表 21 行复算 **0 偏差**

B1 8.59 / B2 8.59 / B3 14.86 / B4 15.52 / C1 7.58 / C2 7.26 / C3 6.70 / L1 7.77 / S1 6.33 / S2 5.59 / G1 6.25 / V1 7.09 / F1 7.25 / X1 7.54 / X2 13.62 / E1 6.50 / D1 8.22 / D2 3.36 / K1 7.77 / R1反 3.15 / R2反 2.85——复算值与表值全部一致（±0.005 容差内），与阶段零终审"21 值 0 偏差"结论相互独立吻合。K1 与 L1 同配同值属定义使然（同为链接蓝/卡片白，用途分别标注），非错误。

**结论：§3.4 表数值可信，可作为 frontend-dev 写 CSS 变量的数值基线**（但须连同 2.3 的修正项一起交付）。

### 2.2 结果二：token 色值一致性抽查（无矛盾）

> **计数口径注记（2026-11-13 补，lead 批准）**：本岗审核对象实测为「**色值 token 21 条**」——`tokens.css` 的 CSS 变量条目（20 处裸 hex + 1 个 `var(--paper-muted)` 引用，去重 18 个值），逐一与修订版规范 §3.1–§3.3 比对一致；lead 曾提及「25 个值」，**其构成口径本岗无从复现，未标注为已核实**——请 lead 给出 25 的清点对象（如含 §3.4 反例行的否决用色 #FACC15/#DC2626/#999999 与 Museum 原值等非常驻 token 的全文 hex 计数）后由本岗补一次全量比对。两数不构成矛盾前，回归判定一律以 tokens.css 21 条为准。

`#8E2430`/`#7A1E28`/`#F8EEEC`/`#1F2430`/`#FAFAF9`/`#F1F1EF`/`#475569`/`#E3E1DC`/`#1E4FA3`/`#8A5300`/`#FAF0DC`/`#166534`/`#EAF2EC`/`#92400E`/`#33526B`/`#A02020`/`#F8E8E8` 全文出现位置逐一核对，同一 token 无两处不同值；lead 裁决后的"审核台拒答=深蓝灰"在 §3.3/§5.8/§6.2/§9 四处表述一致；`#F8E8E8` 现仅存在于 --error-red 浅底（技术故障场景），无残留误用。字号阶梯 12/14/16/18/24/32 全封闭，正文未出现阶梯外字号（Word 12pt 为打印语境显式豁免）。

### 2.3 结果三：发现清单（按严重度）

| 编号 | 严重度 | 位置 | 发现 | 处置建议（不代改，归口规范维护者） |
|---|---|---|---|---|
| **F1** | **Important** | §3.2 `--brand-red-tint` 行 | 断言"底上文字全部 ≥7:1"**不成立**：该浅红底上引用灰实测 **6.65:1**、链接蓝 **6.82:1**（均 ≥4.5 但 <7）；仅墨色 13.62 与品牌红 7.54 达 7。此句会被阶段五/八按 AAA 口径验收而必炸 | 改为"底上正文文字 ≥4.5:1（证据表缺行，见 F2）；如需 AAA 需限制该底上的前景白名单" |
| **F2** | Minor | §3.4 表 vs 正文 | 5 个正文依赖的搭配无证据行：tint 底上 灰/蓝/蓝灰（6.65/6.82/7.20）、琥珀底上链接蓝上标（6.87，§5.1.2 冲突句依赖）、琥珀底上需修改橙褐（6.27，§5.8"琥珀底"依赖）、边框灰/页面底（1.25，§3.1/§6.4 引用"计算值 1.25:1"但表无此行）、hover 深红白字（10.27，§3.2）。数值本身经补算全部满足所应遵循的判定线 | §3.4 表补行，或声明"表外搭配由验收脚本现算" |
| **F3** | Minor | §1 表（A3 行）vs §6.1 | 焦点环口径不一：§1 采纳清单写"3–4px 焦点环"，§6.1 实施条款定 `outline: 2px`（引 `Focus Appearance` 规则"至少 2 CSS px"）。实施值 2px 合规，但与采纳表述差一档 | §6.1 改为"≥2px，建议 2–4px"或统一 3px |
| **F4** | Minor | §5.3 | 待考区标线 `#A9824A` 是**无 token 名裸色值**（§3.1–3.3 未登记），与自引 `color-semantic`（"组件不用 raw hex"）原则冲突；frontend-dev 写 tokens.css 时无名可引 | 登记为 `--pending-line` 类 token 后再进 tokens.css |
| **F5** | Minor | §4.2 首句 | "约 1.25 模数比"表述不实：12/14/16/18/24/32 相邻比为 1.125–1.33 不等比（该阶梯系检索规则示例原样采纳，非模数构造）| 改述为"采用规则示例阶梯，非严格模数" |
| **F6** | Minor | §3.3 `--revise` 行备注 | 备注称需修改与存疑同底色 `#FAF0DC`、"若同屏则以边纹区分（§6.4）"，但 §6.4 条文未包含底色纹理规则——交叉引用落空（实算文字对比度本身达标，F2 之 6.27） | §6.4 补纹理规则，或同屏场景直接区分底色 |

**Critical：0。** 结论：数值层可信（21/21 + 补算 8 项全过各自判定线），矛盾集中在**文字性断言与证据表的覆盖范围**（F1 必须修，F2–F6 登记待规范维护者处理——本岗无修改权限，按纪律不动 `docs/设计规范.md`）。

---

## 3. 人工勾选项（预留区 · frontend-dev 追加）

> 本小节由 frontend-dev 补充脚手架阶段的人工核对勾选项；visual-qa 后续实审时仅引用不代写。

（待追加）

### 3.1 阶段零F 壳阶段人工目测单（2026-11-13，frontend-dev）

> 自动化已覆盖：C1/C3/B5/A2 子集/A6 skip-link（`tests/e2e/visual-redlines.spec.ts`，Playwright 3 视口 15 例）、B1/S5 红线（vitest）、token 层对比度与层叠劫持（`tokens.test.ts` 33 项）。以下条目**无法可靠自动化**，验收时人工逐项勾。格式：**检查什么 → 通过标准**。

- [ ] **P1（B5 残余·版式气质）**：向 mock 提问「飞夺泸定桥」触发拒答区截图 → 对照规范 §5.1.4 线框读感：像"图书馆员的说明"而非"报错弹窗"；无红色系视觉重量（灰度打印后仍成立）。
- [ ] **P2（B6 残余·拒答不含猜测）**：通读拒答文案与参考卡标题 → 没有任何关于被问对象的事实句（哪怕带"可能"）；「仅参考，不构成对该问题的回答」以 16px 正文呈现、未被灰字弱化。
- [ ] **P3（A2 残余·裸史实句）**：壳阶段 mock 答案全部为〔契约样例〕占位 → 人工确认页面不存在任何"看起来像真实史实陈述"的句子；阶段三起改为真实长答案随机抽 10 条读。
- [ ] **P4（A1 残余·灰度）**：问答页与冲突区打印为灰度 → 记载一/记载二、存疑◇、拒答ℹ、电子书/文章徽标仅靠形状+文字仍可区分（配色外信息不丢）。
- [ ] **P5（示例问题 44px 触摸区）**：DevTools 量测 sample chips 与拒答区 chips → 实际渲染高度 ≥44px（组件已写 min-height:44px，目测无内容撑矮）。
- [ ] **P6（顶栏窄屏）**：375px 视口顶栏 → 副题隐藏、导航可横滚、无整页横向滚动（清单 A12 目测部分）。
- [ ] **P7（演示话术）**：按 RUNBOOK 演示一遍 → 开场口头声明「数据为契约样例，真实回答在阶段三接入」被听众能复述；页面 mock 横幅常驻可见。
- [ ] **P8（两类拒答的观感判定，阶段零 lead 批准新增，2026-11-13）**：**判定动作**——找两名未读过代码的复核人（学生/教师各一），依次实际触发「未收录」（问飞夺泸定桥）与「无证据」（问含"可用记载"入口）两个拒答页，各答三问，记录回答原文与屏幕照片：① "这是系统出错了，还是系统在说明情况？凭什么是？"——两页均须答"说明"（R3 观感在两类拒答上都成立才算过）；② "这两页各自说没答上来的理由是什么？"——须能从页面文字复述出「来源里没有记载」与「有来源但找不到支持的记载」的区别，不得靠猜；③ "这两页是同一种情况还是两种情况？"——**接受**"都是内容边界、理由不同"，**判负**回答含"报错/故障/坏了"或"第二页更严重"。通过标准：两名复核人 ①② 全对且 ③ 无判负表述。⚠ 设计意图注记：两类拒答**视觉同族是故意的**（同 ℹ + 同中性底 = 同一"能力边界说明"族），本项不是要求把它们用颜色拉开——措辞不互换已由 e2e D4 用例锁死，本项只判机判不了的感知；若复核人 ③ 反馈"误以为两页严重程度不同"，记录并上报 lead，不得自行改色。

**已知限制（壳阶段刻意不做，勿按不通过记）**：冲突句琥珀底行内样式（C5，阶段三接答案结构时做）；超时降级说明条（§7 矩阵，阶段三）；骨架屏 >1s 计时逻辑（§5.1.1，阶段三）；`--pending-line` token（阶段五时间轴用）；审核台/地图/时间轴组件（阶段五~七）。
**N-4 待办（review-F2，lead 指定登记于此，阶段三/五开工前必读）**：`SourceCard` 对 `mediaKind='unknown'`（登记表出现新载体，如「缩微胶片」）目前走 link 图标兜底、且 URL 只作纯文本不可点。触发条件=白名单加入非「电子书/文章」载体；届时须补专用 SVG 徽标 + 可点定位，并按 R4 三通道补进本清单 B1 判据。组件内注释见 `frontend/src/components/SourceCard.vue` 的 N-4 段。

### 3.2 错误红使用分界定稿（lead 裁决 2026-11-13，写给阶段三接手人）

**判据一句话**：红色（`--error-red`/`--error-red-bg`/⊗/`role="alert"`）只出现在**「可重试的坏」**——HTTP 非 2xx、超时、解析失败等技术故障；**绝不出现在「正常地说没有」**——`status=200 && refusal=true` 的内容拒答一律走深蓝灰中性系（§5.1.4/红线 R3/I5 同源）。

- **护栏（硬）**：阶段三接真接口后，前端**禁止对 `refusal=true` 的 200 响应 throw**；拒答是正确答案形态，走 `RefusalNotice` 分支。`toAnswerModel` 的防御 throw 只应针对违约结构（如 `ConflictItem.sides ≠2`）。
- 现状落点：`AskView.vue` 技术故障态（⊗+重试+`role=alert`+错误红）与 `RefusalNotice.vue`（ℹ+status+`--refusal-ink`）互斥渲染；`tests/ask-view.test.ts`、e2e `B5` 用例双向锁死。
- `suggestions: list[str]` 撑不住「带出处的参考项」——阶段三契约将升级为对象数组或新增 `reference_cards`；字段定稿前前端不得自造字段名（J-2 口径，代码注释已固化于 `AskView.vue`/`adapter` 区）。
