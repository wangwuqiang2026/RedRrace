// S6 AskView 集成测试（mock 模式）：提问区→答案区（句末上标）→出处区→冲突区→拒答区互斥，
// 以及「数据为契约样例」的演示纪律语句。真实接口模式只做静态检查（/api/ask 是 501 占位）。
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AskView from '../src/views/AskView.vue'
import { SAMPLE_QUESTIONS } from '../src/api/mock/scenarios'

async function mountAsk() {
  const w = mount(AskView, { attachTo: document.body })
  await flushPromises()
  return w
}

describe('AskView（mock 版式演示）', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    vi.stubEnv('VITE_USE_MOCK', '1')
  })

  it('未提问状态：输入框 + 示例问题快捷入口（4 个覆盖四版式，button 形态可键盘操作；44px 热区归 e2e/人工）', async () => {
    const w = await mountAsk()
    expect(w.find('input[type=search]').exists()).toBe(true)
    const chips = w.findAll('[data-test=sample-chip]')
    expect(chips.length).toBe(SAMPLE_QUESTIONS.length)
    expect(chips.length).toBe(4)
    for (const c of chips) expect(c.element.tagName.toLowerCase()).toBe('button')
  })

  it('mock 模式横幅：数据为契约样例，真实回答在阶段三接入（S9 演示纪律）', async () => {
    const w = await mountAsk()
    expect(w.text()).toContain('数据为契约样例')
    expect(w.text()).toContain('阶段三')
  })

  it('正常场景：答案区 role=status，句末渲染可聚焦上标，出处区卡片列表齐备', async () => {
    const w = await mountAsk()
    await w.find('[data-test=sample-chip]').trigger('click') // 第 1 个示例=正常回答
    await flushPromises()
    const answer = w.find('[data-test=answer]')
    expect(answer.attributes('role')).toBe('status')
    expect(answer.findAll('sup a[data-test=cite-ref]').length).toBe(2)
    const cards = w.findAll('#sources .source-card')
    expect(cards.length).toBe(2)
    // 上标锚点指向存在的卡片（A2 自动化子集）
    for (const sup of w.findAll('sup a[data-test=cite-ref]')) {
      const href = sup.attributes('href')!
      expect(document.querySelector(href)).not.toBeNull()
    }
  })

  it('冲突场景：冲突区渲染 ConflictPair，两卡等权且 source_id 升序', async () => {
    const w = await mountAsk()
    await w.findAll('[data-test=sample-chip]')[1].trigger('click') // 第 2 个示例=冲突
    await flushPromises()
    const conflict = w.find('[data-test=conflict]')
    expect(conflict.exists()).toBe(true)
    const cards = conflict.findAll('.source-card')
    expect(cards.length).toBe(2)
    expect(cards[0].attributes('data-source-id')).toBe('S002')
    expect(cards[1].attributes('data-source-id')).toBe('S003')
    // I-1（review-F2）：正向断言「无内联样式」可破；旧 toBe(toBe-undefined) 写法永真已废弃。
    // 等权强判据在 e2e computed style（visual-redlines C1）。
    expect(cards[0].attributes('style')).toBeUndefined()
    expect(cards[1].attributes('style')).toBeUndefined()
  })

  it('拒答场景：拒答区出现且与答案区互斥（§5.1.4）', async () => {
    const w = await mountAsk()
    await w.findAll('[data-test=sample-chip]')[2].trigger('click') // 第 3 个示例=未收录拒答
    await flushPromises()
    expect(w.find('[data-test=refusal]').exists()).toBe(true)
    expect(w.find('[data-test=answer]').exists()).toBe(false)
  })

  it('D4 封闭集：no_evidence 场景可达且两类句子不互换（第 4 示例→无证据系句）', async () => {
    const w = await mountAsk()
    await w.findAll('[data-test=sample-chip]')[3].trigger('click')
    await flushPromises()
    const zone = w.find('[data-test=refusal]').text()
    expect(zone).toContain('这个问题暂时找不到可用记载') // 主句逐字
    expect(zone).toContain('已登记的来源中找不到可支持的记载，为避免编造，不作回答') // 说明句逐字
    expect(zone).not.toContain('当前知识库未收录') // 不许把 not_covered 主句换进来
    // 反向：第 3 示例（未收录系）不得出现无证据系主句
    w.unmount()
    document.body.innerHTML = ''
    const w2 = await mountAsk()
    await w2.findAll('[data-test=sample-chip]')[2].trigger('click')
    await flushPromises()
    expect(w2.find('[data-test=refusal]').text()).not.toContain('暂时找不到可用记载')
  })

  it('手输问题走同一 mock 分发：未知问题 → 拒答区', async () => {
    const w = await mountAsk()
    await w.find('input').setValue('完全无关的问题')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[data-test=refusal]').exists()).toBe(true)
  })

  it('接口模式（VITE_USE_MOCK=0）不发真实请求到 501：仅静态确认开关读取自 env（联调等阶段三）', async () => {
    vi.stubEnv('VITE_USE_MOCK', '0')
    const w = await mountAsk()
    expect(w.text()).not.toContain('数据为契约样例')
    vi.stubEnv('VITE_USE_MOCK', '1')
  })

  // ── J-2（lead 2026-11-13 整改）：拒答区 chips 必须是契约字段 answer.suggestions 的消费者，
  //    不得绑前端本地常量；注册来源数拿不到就不许说「0 个来源」──
  function stubRefusalFetch(suggestions: string[]) {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        refusal: true, refusal_reason: 'not_covered', answer: '',
        suggestions, citations: [], conflicts: [], elapsed_ms: 5,
      }),
    }))
  }

  it('J-2：真实模式 suggestions 非空 → 拒答 chips 逐字来自 answer.suggestions（非前端常量）', async () => {
    vi.stubEnv('VITE_USE_MOCK', '0')
    stubRefusalFetch(['契约建议甲问题？', '契约建议乙问题？'])
    const w = mount(AskView, { attachTo: document.body })
    await w.find('input').setValue('任意问题')
    await w.find('form').trigger('submit')
    await flushPromises()
    const chips = w.findAll('[data-test=suggest-chip]')
    expect(chips.map((c) => c.text())).toEqual(['契约建议甲问题？', '契约建议乙问题？'])
    for (const c of chips) expect(SAMPLE_QUESTIONS).not.toContain(c.text())
    vi.unstubAllGlobals()
    vi.stubEnv('VITE_USE_MOCK', '1')
  })

  it('J-2：真实模式注册数无来源 → 文案不得出现「0 个来源」类错话（宁可少说）', async () => {
    vi.stubEnv('VITE_USE_MOCK', '0')
    stubRefusalFetch(['甲？'])
    const w = mount(AskView, { attachTo: document.body })
    await w.find('input').setValue('任意问题')
    await w.find('form').trigger('submit')
    await flushPromises()
    const zone = w.find('[data-test=refusal]').text()
    expect(zone).not.toMatch(/0\s*个来源|已登记的\s*0/)
    expect(zone).toContain('暂无记载')
    vi.unstubAllGlobals()
    vi.stubEnv('VITE_USE_MOCK', '1')
  })
})
