// ============================================================================
// src/api/adapter.ts —— 后端契约字段名的唯一消费层（lead 设计约束 2026-11-13）。
//
// 规则：
//  1. 只有本文件允许出现 `source_id` / `publish_date` / `media_type` 等后端蛇形字段名。
//  2. 组件只吃 src/api/model.ts 的 camelCase 模型；阶段三接真接口时改本文件即可。
//  3. 字段缺失兜底的语义（2026-11-13 契约 I2 后更新）：`AnswerOut` 除 `refusal_reason`
//     外**全部必填**（required=refusal,answer,citations,conflicts,suggestions,elapsed_ms），
//     本层的 `?? []` / `?? ''` / `?? 0` **不是迁就 schema 可选性，而是防御违约的真接口**：
//     后端若发出缺字段的 200 响应，前端按空态渲染并让 S1 型漂移测试在构建期暴露，
//     绝不允许 undefined 直接进入迭代/插值造成白屏。契约保证存在 ≠ 运行期不防。
// 漂移防护：S1 契约测试（tests/contract.test.ts）会把 SourceOut 字段改名并验证
// `pnpm typecheck` 必须失败——即本层就是编译期红线的落点。
// ============================================================================
import type { components } from './types'
import type {
  AnswerModel,
  CitationModel,
  ConflictModel,
  MediaKind,
  SourceCardModel,
} from './model'

type SourceOut = components['schemas']['SourceOut']
type Locator = components['schemas']['Locator']
type Citation = components['schemas']['Citation']
type ConflictItem = components['schemas']['ConflictItem']
type AnswerOut = components['schemas']['AnswerOut']
type AskRequest = components['schemas']['AskRequest']

/**
 * N-3（review-F2）：契约级排序 = **Unicode 码点序**，与后端 Python `sorted()` 同序。
 * `localeCompare` 依赖运行环境 locale/ICU，在符号/大小写混排上会给出不同结果
 * （实测 'S-1' vs 'S_1'：localeCompare=1、码点序=-1），不可用作跨语言契约序。
 */
export function compareSourceCodepoint(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0
}

/** 构造请求体（蛇形字段单层口径：读与写都只在本文件——裁决 4 完整化，N-2）。 */
export function toAskRequest(
  question: string,
  opts: { topK?: number; role?: AskRequest['role'] } = {},
): AskRequest {
  return {
    question,
    top_k: opts.topK ?? 8,
    role: opts.role ?? '学生',
  }
}

function mediaKindOf(mediaType: string): MediaKind {
  if (mediaType === '电子书') return 'book'
  if (mediaType === '文章') return 'article'
  return 'unknown'
}

/** §8 日期口径：10 位日期 → 「YYYY年M月D日」；纯年份保留 4 位；空 → 不详占位。 */
function formatDate(publishDate: string, kind: MediaKind): string {
  if (!publishDate) {
    return kind === 'article' ? '发布日期不详' : '出版年份不详'
  }
  const m = publishDate.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (m) return `${Number(m[1])}年${Number(m[2])}月${Number(m[3])}日`
  return publishDate
}

export function toSourceCardModel(s: SourceOut, locator?: Locator): SourceCardModel {
  const kind = mediaKindOf(s.media_type)
  const url = s.url_or_path ? s.url_or_path : null
  let locatorText: string | null = null
  if (kind === 'article') {
    // 文章：定位字段=原文链接（§5.1.3）
    locatorText = url
  } else {
    // 电子书：页码 > 章节路径 > 链接 > 无（组件显示「定位待补」）
    if (locator?.page != null) locatorText = `第 ${locator.page} 页`
    else if (locator?.heading_path?.length) locatorText = locator.heading_path.join(' · ')
    else locatorText = url
  }
  return {
    sourceId: s.source_id,
    mediaKind: kind,
    mediaLabel: s.media_type || '载体未知',
    title: s.title,
    publisher: s.publisher,
    dateText: formatDate(s.publish_date, kind),
    locatorText,
    url,
    quote: locator?.quote ?? '（无逐字引文——契约不允许该出处进入答案）',
  }
}

export function toCitationModel(c: Citation): CitationModel {
  return {
    index: c.index,
    claim: c.claim,
    source: toSourceCardModel(c.source, c.locator),
  }
}

/**
 * sides 的「条数」与「顺序」分工（权威出处=docs/决策记录/003 §5.2，阶段三接手人必读；
 * compliance-docs 复验 2026-11-13，lead 13:2x 转达更正——此前"第三层"表述作废）：
 *
 * 【条数＝恰好两条：后端契约层拦 + 前端本函数 throw 为防御性第二层】
 *   后端：schemas.py:74 `Field(min_length=2, max_length=2)` + :79 同 id 拒绝，
 *         违反不变式的对象**连构造都过不了**；HTTP 面另见 router.py:17 `response_model`。
 *   前端侧只有两层：openapi-typescript 7.13 不把 min/maxItems 生成定长 tuple
 *         （实测 types.ts:121 = `Citation[]`，全文件 tuple 命中 0）——**类型面上等于无约束**，
 *         故本函数 `sides.length !== 2` throw 是不可撤除的防御性第二道，禁止截断/补位（约束 4）。
 *
 * 【顺序＝恒 source_id 升序：后端「拒绝违约」而非「替调用方重排」，前端排序永远不可撤除】
 *   后端：schemas.py:81-82 在 `ids != sorted(ids)` 时抛错——它兜顺序的方式是让请求/响应**失败**，
 *         绝不是排好序交给前端。
 *   前端：本函数与 ConflictPair 用 `compareSourceCodepoint`（码点序=Python `sorted()` 同序，
 *         N-3/判别对见测试）**始终自己排**；这一层不因契约存在而可省略，也不依赖类型系统（5.1）。
 *
 * 变更纪律（003 §5.3）：类型生成工具替换/升级时必须重跑 visual-qa 三形态实验，
 * 确认拦截层没有假移位（删前端排序仍可见展示退化、喂违约 JSON 能区分谁命中）。
 */
export function toConflictModel(item: ConflictItem): ConflictModel {
  if (item.sides.length !== 2) {
    throw new Error(`ConflictItem.sides 必须恰好两条（契约约定），实际 ${item.sides.length}——拒绝截断或补位`)
  }
  const sorted = [...item.sides].sort((a, b) => compareSourceCodepoint(a.source.source_id, b.source.source_id))
  const sides = sorted.map(toCitationModel).map((c) => c.source)
  return { subject: item.subject, predicate: item.predicate, sides: [sides[0], sides[1]] }
}

export function toAnswerModel(a: AnswerOut): AnswerModel {
  // I2 后 answer/citations/conflicts/suggestions/elapsed_ms 全部必填——下面每个 `??` 的
  // 去留结论统一为**保留**，语义从「迁就旧 schema」改为「防御违约 200」（逐条理由见 §文件头规则 3）：
  //   refusal_reason 的 ?? null 是真实可选归一；answer/citations/conflicts/suggestions/
  //   elapsed_ms 的 ?? 是违约防线（缺省渲染空态，绝不让 undefined 进迭代/插值）。
  const citations = (a.citations ?? []).map(toCitationModel)
  return {
    refusal: a.refusal,
    refusalReason: a.refusal_reason ?? null,
    answer: a.answer ?? '',
    citations,
    conflicts: (a.conflicts ?? []).map(toConflictModel),
    suggestions: a.suggestions ?? [],
    elapsedMs: a.elapsed_ms ?? 0,
  }
}
