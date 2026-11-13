// S4 SourceCard 测试（清单 B1：出处卡片信息完整，完全可自动化）。
// 字段顺序固定：载体徽标 → 标题 → 发布者·日期 → 定位 → 逐字引文 → 回链（规范 §5.1.3）。
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SourceCard from '../src/components/SourceCard.vue'
import type { SourceCardModel } from '../src/api/model'

const base: SourceCardModel = {
  sourceId: 'S002',
  mediaKind: 'book',
  mediaLabel: '电子书',
  title: '红军长征记',
  publisher: '解放军出版社',
  dateText: '2026',
  locatorText: '第 237 页',
  url: null,
  quote: '〔契约样例引文——逐字原文在阶段三接真实语料后替换〕',
}

describe('SourceCard 电子书版式', () => {
  it('渲染全部必填字段且顺序固定', () => {
    const w = mount(SourceCard, { props: { src: base } })
    const order = w.findAll('[data-field]').map((el) => el.attributes('data-field'))
    expect(order).toEqual(['badge', 'title', 'publisher-date', 'locator', 'quote', 'backlink'])
    expect(w.text()).toContain('电子书')
    expect(w.text()).toContain('红军长征记')
    expect(w.text()).toContain('解放军出版社')
    expect(w.text()).toContain('2026')
    expect(w.text()).toContain('第 237 页')
    expect(w.text()).toContain('契约样例引文')
    expect(w.text()).toContain('S002')
  })

  it('徽标=SVG 图标+文字双通道（R4），无 emoji', () => {
    const w = mount(SourceCard, { props: { src: base } })
    const badge = w.find('[data-field=badge]')
    expect(badge.find('svg').exists()).toBe(true)
    expect(badge.text()).toContain('电子书')
    expect(badge.text()).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u)
  })

  it('卡片带 id 锚点与 data-source-id（CitationMark 回链 + C3 排序判据）', () => {
    const w = mount(SourceCard, { props: { src: base } })
    expect(w.attributes('id')).toBe('source-S002')
    expect(w.attributes('data-source-id')).toBe('S002')
    expect(w.classes()).toContain('source-card')
  })
})

describe('SourceCard 文章版式', () => {
  const art: SourceCardModel = {
    ...base,
    sourceId: 'S001',
    mediaKind: 'article',
    mediaLabel: '文章',
    title: '湖南郴州建成红军长征档案数据库',
    publisher: '中国档案报',
    dateText: '2026年10月19日',
    locatorText: 'http://www.zgdazxw.com.cn/2026-10/19/content_505878.html',
    url: 'http://www.zgdazxw.com.cn/2026-10/19/content_505878.html',
  }

  it('标题+发布机构+发布日期+可点击链接全部渲染', () => {
    const w = mount(SourceCard, { props: { src: art } })
    expect(w.text()).toContain('文章')
    expect(w.text()).toContain('湖南郴州建成红军长征档案数据库')
    expect(w.text()).toContain('中国档案报')
    expect(w.text()).toContain('2026年10月19日')
    const a = w.get('[data-field=locator] a')
    expect(a.attributes('href')).toBe(art.url)
    expect(a.attributes('target')).toBe('_blank')
    expect(a.attributes('rel')).toContain('noopener')
  })

  it('页码与链接均缺失 → 显示「定位待补」不留空（简报 S4）', () => {
    const w = mount(SourceCard, { props: { src: { ...base, locatorText: null, url: null } } })
    expect(w.get('[data-field=locator]').text()).toContain('定位待补')
  })

  it('缺字段走「××不详」占位不留空（B1）', () => {
    const w = mount(SourceCard, { props: { src: { ...base, dateText: '出版年份不详' } } })
    expect(w.get('[data-field=publisher-date]').text()).toContain('出版年份不详')
  })
})
