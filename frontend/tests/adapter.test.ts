// S4 适配层测试：后端契约形状（SourceOut/AnswerOut/ConflictItem）→ 前端 props 模型。
// lead 设计约束：「读后端字段名」的代码只允许存在于 src/api/adapter.ts 这一层，
// 组件不接受后端原始字段名——阶段三接真接口时返工面收敛到适配层。
import { describe, it, expect } from 'vitest'
import type { components } from '../src/api/types'
import { toSourceCardModel, toConflictModel, toAnswerModel } from '../src/api/adapter'

type SourceOut = components['schemas']['SourceOut']
type Locator = components['schemas']['Locator']
type Citation = components['schemas']['Citation']
type ConflictItem = components['schemas']['ConflictItem']
type AnswerOut = components['schemas']['AnswerOut']

const book: SourceOut = {
  source_id: 'S002',
  title: '红军长征记',
  publisher: '解放军出版社',
  publish_date: '2026',
  url_or_path: 'https://www.dswxyjy.org.cn/n1/2026/1015/c434085-40815320.html',
  access_date: '2026-11-13',
  license_note: '公开出版物',
  corpus_tier: '核心',
  media_type: '电子书',
  verified: true,
}
const article: SourceOut = {
  ...book,
  source_id: 'S001',
  title: '湖南郴州建成红军长征档案数据库',
  publisher: '中国档案报',
  publish_date: '2026-10-19',
  media_type: '文章',
}
const loc: Locator = { quote: '〔契约样例引文〕', page: 237 }

describe('S4 适配层：契约 → props 模型', () => {
  it('电子书：mediaKind=book，页码定位渲染为「第 N 页」', () => {
    const m = toSourceCardModel(book, loc)
    expect(m.mediaKind).toBe('book')
    expect(m.mediaLabel).toBe('电子书')
    expect(m.locatorText).toBe('第 237 页')
    expect(m.dateText).toBe('2026')
  })

  it('电子书无页码但有章节路径时用章节定位；两者皆缺 → locatorText=null（组件负责显示「定位待补」）', () => {
    const byHeading = toSourceCardModel(book, { quote: 'q', heading_path: ['第三章', '第二节'] })
    expect(byHeading.locatorText).toBe('第三章 · 第二节')
    const none = toSourceCardModel({ ...book, url_or_path: '' }, { quote: 'q' })
    expect(none.locatorText).toBeNull()
  })

  it('文章：mediaKind=article，日期转 YYYY年M月D日（§8），链接进 url', () => {
    const m = toSourceCardModel(article, { quote: 'q', paragraph: 3 })
    expect(m.mediaKind).toBe('article')
    expect(m.dateText).toBe('2026年10月19日')
    expect(m.url).toBe(article.url_or_path)
    expect(m.locatorText).toBe(article.url_or_path)
  })

  it('缺 publish_date → 电子书「出版年份不详」，文章「发布日期不详」（B1：禁止留空或猜测）', () => {
    expect(toSourceCardModel({ ...book, publish_date: '' }, loc).dateText).toBe('出版年份不详')
    expect(toSourceCardModel({ ...article, publish_date: '' }, loc).dateText).toBe('发布日期不详')
  })

  it('未知 media_type 不崩溃：mediaKind=unknown，徽标文字取原始值', () => {
    const m = toSourceCardModel({ ...book, media_type: '缩微胶片' }, loc)
    expect(m.mediaKind).toBe('unknown')
    expect(m.mediaLabel).toBe('缩微胶片')
  })

  it('ConflictItem.sides 乱序输入 → 模型恒为 source_id 升序（lead 裁决 5 的适配层镜像）', () => {
    const sides: Citation[] = [
      { index: 2, claim: 'B', locator: loc, source: { ...book, source_id: 'S031' }, verified: true },
      { index: 1, claim: 'A', locator: loc, source: { ...book, source_id: 'S012' }, verified: true },
    ]
    const c: ConflictItem = { subject: '某事件', predicate: '参加人数', sides }
    const m = toConflictModel(c)
    expect(m.sides.map((s) => s.sourceId)).toEqual(['S012', 'S031'])
  })

  // J-1（lead 2026-11-13 整改，约束 4「冲突不取舍」）：>2 条 sides 必须抛错。
  // 静默截断=替用户丢弃记载，即使后端 schema 兜住（min/max_length=2），前端截断仍会掩盖上游 bug，
  // 让「三个来源打架」这种真情况永远看不见。
  it('J-1：sides 恰好三条 → 必须抛错，绝不返回两张卡', () => {
    const sides: Citation[] = [
      { index: 1, claim: 'A', locator: loc, source: { ...book, source_id: 'S001' }, verified: true },
      { index: 2, claim: 'B', locator: loc, source: { ...book, source_id: 'S002' }, verified: true },
      { index: 3, claim: 'C', locator: loc, source: { ...book, source_id: 'S003' }, verified: true },
    ]
    expect(() => toConflictModel({ subject: 'S', predicate: 'P', sides })).toThrow(/恰好两条/)
  })

  it('J-1：sides 一条 → 同样抛错（双向锁死，不是只防 >2）', () => {
    const sides: Citation[] = [
      { index: 1, claim: 'A', locator: loc, source: { ...book, source_id: 'S001' }, verified: true },
    ]
    expect(() => toConflictModel({ subject: 'S', predicate: 'P', sides })).toThrow(/恰好两条/)
  })

  // N-3（review-F2）：契约级排序必须是 Unicode 码点序（与后端 Python sorted() 同序）。
  it('N-3：卡序=码点序而非 localeCompare（判别对 S-1/S_1，两序不同）', () => {
    const mk = (id: string): Citation => ({ index: 1, claim: id, locator: loc, source: { ...book, source_id: id }, verified: true })
    // 判别力前提：若 localeCompare 与码点序一致，本用例就空转——先锁死分歧的存在
    expect('S-1'.localeCompare('S_1'), 'localeCompare 与码点序对判别对必须不同序').toBeGreaterThan(0)
    const m = toConflictModel({ subject: 'S', predicate: 'P', sides: [mk('S_1'), mk('S-1')] })
    expect(m.sides.map((s) => s.sourceId)).toEqual(['S-1', 'S_1']) // '-'(0x2D) < '_'(0x5F)
  })

  it('防御违约响应：required 全集之外仍逐字段兜底不崩（I2 后语义=防真接口违约，非迁就可选性）', () => {
    // 新契约 required=['refusal','answer','citations','conflicts','suggestions','elapsed_ms']。
    // 本用例故意发一个只含 refusal 的**违约**响应（as 断言绕过编译），验证防线渲染空态而非崩溃。
    const partial = { refusal: true } as AnswerOut
    const m = toAnswerModel(partial)
    expect(m.refusal).toBe(true)
    expect(m.answer).toBe('')
    expect(m.citations).toEqual([])
    expect(m.conflicts).toEqual([])
    expect(m.suggestions).toEqual([])
    expect(m.refusalReason).toBeNull()
  })
})
