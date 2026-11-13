// S5 ConflictPair 红线测试（简报要求「测试即验收」，两条红线原文如下，注释即简报伪代码）。
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import ConflictPair from '../src/components/ConflictPair.vue'
import type { ConflictModel, SourceCardModel } from '../src/api/model'

function card(over: Partial<SourceCardModel>): SourceCardModel {
  return {
    sourceId: 'S012',
    mediaKind: 'book',
    mediaLabel: '电子书',
    title: '红军长征记',
    publisher: '解放军出版社',
    dateText: '1935',
    locatorText: '第 237 页',
    url: null,
    quote: '〔契约样例引文〕',
    ...over,
  }
}

/** 两条来源年份不同的冲突数据。
 * I-2（review-F2）：夹具 sides 故意为 **乱序**（S031 在前）——若基线已升序，
 * 「调换年份卡序不变」删掉排序代码也照样绿，判据就空转了。乱序输入让排序必须存在。 */
function twoSourcesWithDifferentYears(): ConflictModel {
  return {
    subject: '红军长征',
    predicate: '参加人数',
    sides: [
      card({ sourceId: 'S031', title: '中国共产党历史（第三卷上册）', publisher: '中共党史出版社', dateText: '1949' }),
      card({ sourceId: 'S012', dateText: '1935' }),
    ],
  }
}

function swapYears(c: ConflictModel): ConflictModel {
  const [a, b] = c.sides
  return { ...c, sides: [{ ...a, dateText: b.dateText }, { ...b, dateText: a.dateText }] }
}

function mountConflictPair(conflict: ConflictModel) {
  return mount(ConflictPair, { props: { conflict } })
}

describe('ConflictPair（红线 R1/C1/C3）', () => {
  it('两条来源视觉等权', () => {
    // I-1（review-F2）：正向形式——两张 .source-card **谁都不许有内联样式**（可破的断言）。
    // 旧写法 expect(a).toBe(b) 在两侧同为 undefined 时永真，是空断言。
    const cards = mountConflictPair(twoSourcesWithDifferentYears()).findAll('.source-card')
    expect(cards.length).toBe(2)
    expect(cards[0].attributes('style')).toBeUndefined()
    expect(cards[1].attributes('style')).toBeUndefined()
    expect(cards[0].classes()).not.toContain('muted')
    // 真正守住「等权」的是下面这条 classes() 全等（任一卡多/少一个类即炸）
    // + e2e computed style 六属性成对相等（visual-redlines.spec.ts C1）。
    expect(cards[0].classes()).toEqual(cards[1].classes())
  })

  it('排序与可信度无关：调换出版年份后卡序不变（恒为 source_id 升序）', () => {
    // 夹具 sides 乱序（I-2）：本用例与下一行期望 ['S012','S031'] 必须依赖排序代码才成立
    const a = mountConflictPair(swapYears(twoSourcesWithDifferentYears()))
      .findAll('.source-card')
      .map((c) => c.attributes('data-source-id'))
    const b = mountConflictPair(twoSourcesWithDifferentYears())
      .findAll('.source-card')
      .map((c) => c.attributes('data-source-id'))
    expect(a).toEqual(b)
    expect(a).toEqual(['S012', 'S031']) // 恒为 source_id 升序（lead 裁决 5）
  })

  it('输入乱序也恒 source_id 升序（组件层防御，DOM 顺序=视觉顺序）', () => {
    const shuffled: ConflictModel = {
      ...twoSourcesWithDifferentYears(),
      sides: [
        card({ sourceId: 'S031', dateText: '1990' }),
        card({ sourceId: 'S007' }),
      ],
    }
    const ids = mountConflictPair(shuffled).findAll('.source-card').map((c) => c.attributes('data-source-id'))
    expect(ids).toEqual(['S007', 'S031'])
  })

  it('标签仅「记载一/记载二」，禁用词零命中（C2/C4）', () => {
    const text = mountConflictPair(twoSourcesWithDifferentYears()).text()
    expect(text).toContain('记载一')
    expect(text).toContain('记载二')
    expect(text).not.toMatch(/更可信|推荐|较新来源|仅供参考/)
    expect(text).toContain('两处记载不一致')
  })

  it('提示条标题含主体与谓词中文名，外层单色底不区分两卡（§5.2 第 5 条）', () => {
    const w = mountConflictPair(twoSourcesWithDifferentYears())
    expect(w.get('[data-test=conflict-title]').text()).toContain('红军长征')
    expect(w.get('[data-test=conflict-title]').text()).toContain('参加人数')
    expect(w.find('[data-test=conflict]').classes()).toContain('conflict-band')
  })

  // J-1 组件层镜像：即使上游防线失守塞进三条，组件也**不得丢弃记载**——
  // 宁可显示「记载三」暴露异常，不可静默截断把三源打架粉饰成两源。
  it('J-1：喂入三条 sides（绕过适配层）→ 三卡全部渲染，无一张被丢弃', () => {
    const three = {
      subject: 'S',
      predicate: 'P',
      sides: [
        card({ sourceId: 'S009' }),
        card({ sourceId: 'S003' }),
        card({ sourceId: 'S021' }),
      ],
    }
    const w = mountConflictPair(three as never)
    const ids = w.findAll('.source-card').map((c) => c.attributes('data-source-id'))
    expect(ids).toEqual(['S003', 'S009', 'S021']) // 全渲染 + 仍恒升序
    expect(w.text()).toContain('记载三')
  })
})
