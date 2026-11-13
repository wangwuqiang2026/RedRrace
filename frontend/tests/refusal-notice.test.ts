// S6 RefusalNotice 测试（红线 R3/B5/B6/I5 的组件层判据，按 视觉验收-阶段零F §1.2 伪代码）。
// 断言四条硬约束：role 非 alert；禁词零命中；ℹ info 图标而非 ⊗/alert 图标；中性 token 类而非错误红。
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mount } from '@vue/test-utils'
import RefusalNotice from '../src/components/RefusalNotice.vue'
import type { SourceCardModel } from '../src/api/model'

const refs: SourceCardModel[] = [
  {
    sourceId: 'S004',
    mediaKind: 'article',
    mediaLabel: '文章',
    title: '万里征途入诗行',
    publisher: '中国共产党新闻网',
    dateText: '2026年11月12日',
    locatorText: 'http://cpc.people.com.cn',
    url: 'http://cpc.people.com.cn',
    quote: '〔契约样例引文〕',
  },
]

function mountNotice(props = {}) {
  return mount(RefusalNotice, {
    props: {
      reason: 'not_covered',
      sourceCount: 5,
      references: refs,
      suggestions: ['郴州档案数据库', '万里征途入诗行', '长沙地方志'],
      ...props,
    },
  })
}

describe('RefusalNotice（R3：像说明不像报错）', () => {
  it('root 是 role=status，绝不出现 role=alert', () => {
    const w = mountNotice()
    expect(w.attributes('role')).toBe('status')
    expect(w.find('[role=alert]').exists()).toBe(false)
  })

  it('B5 禁词零命中：错误/失败/异常/无法处理/出错', () => {
    const text = mountNotice().text()
    expect(text).not.toMatch(/错误|失败|异常|无法处理|出错/)
  })

  it('B5 措辞白名单：「未收录」「暂无记载」；B6 参考卡上方固定免责句原文', () => {
    const text = mountNotice().text()
    expect(text).toContain('当前知识库未收录')
    expect(text).toContain('暂无记载')
    expect(text).toContain('仅参考，不构成对该问题的回答')
  })

  it('ℹ info 图标存在（三通道：图标+文字+颜色），⊗/alert 类图标零命中', () => {
    const w = mountNotice()
    expect(w.find('[data-icon=info]').exists()).toBe(true)
    expect(w.find('[data-icon=x-circle]').exists()).toBe(false)
    expect(w.find('[data-icon=alert-triangle]').exists()).toBe(false)
  })

  it('样式 token 纪律（N-5 修正）：组件源码 style 块不引用错误红 token', () => {
    // 旧写法 w.html() 不含 scoped <style>，对颜色判据空转；真判据在 e2e B5 computed 值。
    // 这里改读源文件 style 块，断言 token 集合不含 error-red。
    const src = readFileSync(resolve('src/components/RefusalNotice.vue'), 'utf8')
    const style = src.match(/<style[^>]*>([\s\S]*?)<\/style>/g)!.join('\n')
    expect(style).not.toMatch(/error-red/)
    expect(style).toMatch(/var\(--refusal-ink\)/)
    expect(style).toMatch(/var\(--refusal-bg\)/)
    expect(mountNotice().classes()).toContain('refusal-notice')
  })

  it('无证据拒答（no_evidence）给出对应说明文案，同样非报错', () => {
    const text = mountNotice({ reason: 'no_evidence' }).text()
    expect(text).toContain('已登记的来源中找不到可支持的记载')
    expect(text).not.toMatch(/错误|失败/)
  })

  it('D4 封闭集：两类主句互斥——not_covered 不含无证据主句，反之亦然', () => {
    expect(mountNotice({ reason: 'not_covered' }).text()).not.toContain('暂时找不到可用记载')
    const t = mountNotice({ reason: 'no_evidence' }).text()
    expect(t).toContain('这个问题暂时找不到可用记载')
    expect(t).not.toContain('当前知识库未收录')
  })

  it('sourceCount=null（真实模式无契约来源）→ 不出现「0 个来源」错话，句子其余齐备', () => {
    const text = mountNotice({ sourceCount: null }).text()
    expect(text).not.toMatch(/0\s*个来源/)
    expect(text).toContain('这些来源中暂无记载')
  })

  it('参考卡片 ≤3 且用 SourceCard 组件渲染（§5.1.4）', () => {
    const many = [refs[0], refs[0], refs[0], refs[0], refs[0]]
    const w = mountNotice({ references: many })
    expect(w.findAll('.source-card').length).toBeLessThanOrEqual(3)
    expect(w.findAll('.source-card').length).toBeGreaterThan(0)
  })

  it('示例问题 chips 点击上抛 suggest 事件（拒答区自助出口）', async () => {
    const w = mountNotice()
    const chip = w.find('[data-test=suggest-chip]')
    expect(chip.exists()).toBe(true)
    await chip.trigger('click')
    expect(w.emitted('suggest')?.[0]).toEqual(['郴州档案数据库'])
  })
})
