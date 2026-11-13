// ============================================================================
// citation-mark.test.ts —— 判定代码归审计方（visual-qa），生产实现归 frontend-dev。
// 依据：docs/设计规范.md §5.1.2（R2 载体）、视觉验收清单 B3/B4、lead 2026-11-13 批准。
// 修改本文件需审计方同意；frontend-dev 的职责是让红项转绿，不是改断言。
// ============================================================================
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import CitationMark from '../src/components/CitationMark.vue'
import SourceCard from '../src/components/SourceCard.vue'
import type { SourceCardModel } from '../src/api/model'

function mountMark(index = 1, sourceId = 'S001', title = '湖南郴州建成红军长征档案数据库') {
  return mount(CitationMark, {
    props: { index, sourceId, sourceTitle: title },
    attachTo: document.body,
  })
}

describe('CitationMark 可达性红线（审计方判定）', () => {
  beforeEach(() => { document.body.innerHTML = '' })

  it('编号是键盘可聚焦的交互元素：a[href] 或有非负 tabindex，出现 tabindex 时严禁 -1', () => {
    const w = mountMark()
    const a = w.get('a[data-test=cite-ref]')
    const hasHref = typeof a.attributes('href') === 'string' && a.attributes('href')!.length > 0
    const tabindex = a.attributes('tabindex')
    if (tabindex !== undefined) {
      expect(Number(tabindex), 'tabindex 显式出现且为 -1：红线不通过（键盘不可达）').toBeGreaterThanOrEqual(0)
    }
    expect(hasHref, '既无 href 也无非负 tabindex：编号不可聚焦，违反 §5.1.2 / R2').toBe(true)
  })

  it('aria-label 语义完整：格式「出处 {n}：{标题}」（中文全角冒号，播报不是裸数字）', () => {
    const w = mountMark(2, 'S002', '红军长征记')
    const label = w.get('a[data-test=cite-ref]').attributes('aria-label')
    expect(label, 'aria-label 缺失：屏幕阅读器只剩裸数字 [2]，违反清单 B3').toMatch(/^出处 2：红军长征记$/)
  })

  it('锚点与 SourceCard 的 id 约定互配：href=#source-{id} ↔ id="source-{id}"（A2 回链闭环）', () => {
    const model: SourceCardModel = {
      sourceId: 'S042', mediaKind: 'book', mediaLabel: '电子书', title: 'T', publisher: 'P',
      dateText: '1935', locatorText: '第 1 页', url: null, quote: 'q',
    }
    const w = mountMark(3, 'S042')
    mount(SourceCard, { props: { src: model }, attachTo: document.body })
    const href = w.get('a[data-test=cite-ref]').attributes('href')
    expect(href).toBe('#source-S042')
    expect(document.querySelector(href!), '上标锚点指向的目标不存在').not.toBeNull()
  })

  it('激活后滚动定位 + 闪烁类在 ≤1.2s 后清除（行为层；样式可见性由下一条断言）', () => {
    vi.useFakeTimers()
    const target = document.createElement('article')
    target.id = 'source-S003'
    target.scrollIntoView = vi.fn()
    document.body.appendChild(target)
    const w = mountMark(3, 'S003')
    w.get('a[data-test=cite-ref]').trigger('click')
    expect(target.scrollIntoView).toHaveBeenCalled()
    expect(target.classList.contains('cite-flash')).toBe(true)
    vi.advanceTimersByTime(1200)
    expect(target.classList.contains('cite-flash')).toBe(false)
    vi.useRealTimers()
    w.unmount()
  })

  it('B4 视觉反馈成立：.cite-flash 的样式规则必须在 src 中真实定义（当前已知红，修复归 frontend-dev）', () => {
    // 上标点击只加类不算完成——无样式则「浅红底闪烁」（规范 §5.1）静默丢失，
    // 定位高亮不可见，清单 B4「有可见高亮」不成立。
    const files: string[] = []
    ;(function walk(dir: string) {
      for (const n of readdirSync(dir)) {
        const p = join(dir, n)
        if (statSync(p).isDirectory()) walk(p)
        else if (/\.(css|vue)$/.test(n)) files.push(p)
      }
    })(resolve('src'))
    const hit = files.some((f) => /\.cite-flash\s*[{:]/.test(readFileSync(f, 'utf8')))
    expect(hit, 'cite-flash 类被 JS 添加但样式表零定义：闪烁不可见（§5.1 / 清单 B4）').toBe(true)
  })

  afterEach(() => { vi.restoreAllMocks(); document.body.innerHTML = '' })
})
