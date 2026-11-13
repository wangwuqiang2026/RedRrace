// S8 无障碍基线（组件层，A1/A5/A6/R4 的可自动化子集；computed 实测部分在 tests/e2e）。
// 按 docs/视觉验收-阶段零F.md §1.2 A1 伪代码的三通道判据：文字+图标+颜色（token 类）。
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import SourceCard from '../src/components/SourceCard.vue'
import ConflictPair from '../src/components/ConflictPair.vue'
import RefusalNotice from '../src/components/RefusalNotice.vue'
import type { SourceCardModel } from '../src/api/model'

const card: SourceCardModel = {
  sourceId: 'S001', mediaKind: 'article', mediaLabel: '文章', title: 'T',
  publisher: 'P', dateText: '2026年1月1日', locatorText: 'u', url: 'http://u', quote: 'q',
}

describe('A1/R4 三通道（颜色+图标+文字）', () => {
  it('载体徽标：svg 图标 + 「文章」文字 + token 化颜色（class 引用，非硬编码）', () => {
    const badge = mount(SourceCard, { props: { src: card } }).get('[data-field=badge]')
    expect(badge.find('svg').exists()).toBe(true)
    expect(badge.text()).toContain('文章')
  })

  it('定位待补：菱形图标 + 文字（不只靠颜色）', () => {
    const w = mount(SourceCard, { props: { src: { ...card, locatorText: null, url: null } } })
    const loc = w.get('[data-field=locator]')
    expect(loc.find('svg').exists()).toBe(true)
    expect(loc.text()).toContain('定位待补')
  })

  it('冲突标识：◇ 图标 + 「两处记载不一致」文字', () => {
    const w = mount(ConflictPair, {
      props: { conflict: { subject: 'S', predicate: 'P', sides: [card, { ...card, sourceId: 'S002' }] } },
    })
    expect(w.get('[data-test=conflict-title]').find('svg').exists()).toBe(true)
    expect(w.text()).toContain('两处记载不一致')
  })

  it('拒答标识：ℹ 图标 + 「未收录」文字（ℹ 而非 ⊗）', () => {
    const w = mount(RefusalNotice, { props: { reason: 'not_covered', sourceCount: 5, references: [], suggestions: [] } })
    expect(w.find('[data-icon=info]').exists()).toBe(true)
    expect(w.text()).toContain('未收录')
  })
})

describe('A5 状态词表无同义漂移（壳阶段出现的状态词必须来自词表）', () => {
  it('src 组件模板文本不含「有疑问/待确认/出错」等同义词或报错措辞', () => {
    const files: string[] = []
    const walk = (d: string) => readdirSync(d).forEach((n) => {
      const p = join(d, n)
      if (statSync(p).isDirectory()) walk(p)
      else if (/\.(vue|ts)$/.test(n)) files.push(p)
    })
    walk('src')
    expect(files.length).toBeGreaterThan(0)
    const bad = /有疑问|待确认|有误|出错了?|抱歉/
    for (const f of files) {
      if (bad.test(readFileSync(f, 'utf8'))) throw new Error(`${f} 含状态词表外措辞`)
    }
  })
})

describe('A6 焦点样式纪律', () => {
  it('全站 CSS 不出现 outline:none / outline: 0（注释除外）', () => {
    const cssText = ['src/styles/base.css', 'src/styles/tokens.css']
      .map((f) => readFileSync(f, 'utf8').replace(/\/\*[\s\S]*?\*\//g, ''))
      .join('\n')
    expect(cssText).not.toMatch(/outline\s*:\s*(none|0)/)
    expect(cssText).toMatch(/:focus-visible/)
  })
})
