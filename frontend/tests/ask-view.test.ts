// S6 AskView 集成测试（阶段三步骤 8：问答页去 mock，走真接口 + fetch 替身）。
// 版式断言不变：提问区→答案区（句末上标）→出处区→冲突区→拒答区互斥。
// 数据来自 src/api/mock 的契约样例 fixtures（只作测试夹具，生产入口已无 mock 分支）。
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import AskView from '../src/views/AskView.vue'
import { SAMPLE_QUESTIONS } from '../src/api/mock/scenarios'
import {
  ANSWER_OK, ANSWER_CONFLICT, ANSWER_REFUSED, ANSWER_REFUSED_NO_EVIDENCE,
} from '../src/api/mock/scenarios'

function stubAnswer(payload: unknown) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => payload,
  }))
}

async function askSample(index: number) {
  const w = mount(AskView, { attachTo: document.body })
  await w.findAll('[data-test=sample-chip]')[index].trigger('click')
  await flushPromises()
  return w
}

describe('AskView（真接口 + 契约样例夹具）', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    stubAnswer(ANSWER_OK)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    vi.unstubAllEnvs()
  })

  it('未提问状态：输入框 + 示例问题快捷入口（4 个覆盖四版式，button 形态可键盘操作）', async () => {
    const w = mount(AskView, { attachTo: document.body })
    await flushPromises()
    expect(w.find('input[type=search]').exists()).toBe(true)
    const chips = w.findAll('[data-test=sample-chip]')
    expect(chips.length).toBe(SAMPLE_QUESTIONS.length)
    expect(chips.length).toBe(4)
    for (const c of chips) expect(c.element.tagName.toLowerCase()).toBe('button')
  })

  it('生产页不再有「数据为契约样例」横幅（mock 入口已删，夹具只在测试）', async () => {
    const w = mount(AskView, { attachTo: document.body })
    await flushPromises()
    expect(w.text()).not.toContain('数据为契约样例')
  })

  it('正常场景：答案区 role=status，句末渲染可聚焦上标，出处区卡片列表齐备', async () => {
    const w = await askSample(0)
    const answer = w.find('[data-test=answer]')
    expect(answer.attributes('role')).toBe('status')
    expect(answer.findAll('sup a[data-test=cite-ref]').length).toBe(2)
    const cards = w.findAll('#sources .source-card')
    expect(cards.length).toBe(2)
    for (const sup of w.findAll('sup a[data-test=cite-ref]')) {
      const href = sup.attributes('href')!
      expect(document.querySelector(href)).not.toBeNull()
    }
  })

  it('冲突场景：冲突区渲染 ConflictPair，两卡等权且 source_id 升序', async () => {
    stubAnswer(ANSWER_CONFLICT)
    const w = await askSample(1)
    const conflict = w.find('[data-test=conflict]')
    expect(conflict.exists()).toBe(true)
    const cards = conflict.findAll('.source-card')
    expect(cards.length).toBe(2)
    expect(cards[0].attributes('data-source-id')).toBe('S002')
    expect(cards[1].attributes('data-source-id')).toBe('S003')
    expect(cards[0].attributes('style')).toBeUndefined()
    expect(cards[1].attributes('style')).toBeUndefined()
  })

  it('拒答场景：拒答区出现且与答案区互斥（§5.1.4）', async () => {
    stubAnswer(ANSWER_REFUSED)
    const w = await askSample(2)
    expect(w.find('[data-test=refusal]').exists()).toBe(true)
    expect(w.find('[data-test=answer]').exists()).toBe(false)
  })

  it('D4 封闭集：no_evidence 场景两类句子不互换', async () => {
    stubAnswer(ANSWER_REFUSED_NO_EVIDENCE)
    const w = await askSample(3)
    const zone = w.find('[data-test=refusal]').text()
    expect(zone).toContain('这个问题暂时找不到可用记载')
    expect(zone).toContain('已登记的来源中找不到可支持的记载，为避免编造，不作回答')
    expect(zone).not.toContain('当前知识库未收录')
    w.unmount()
    document.body.innerHTML = ''
    stubAnswer(ANSWER_REFUSED)
    const w2 = await askSample(2)
    expect(w2.find('[data-test=refusal]').text()).not.toContain('暂时找不到可用记载')
  })

  it('手输问题走同一真接口：未知问题 → 拒答区', async () => {
    stubAnswer(ANSWER_REFUSED)
    const w = mount(AskView, { attachTo: document.body })
    await w.find('input').setValue('完全无关的问题')
    await w.find('form').trigger('submit')
    await flushPromises()
    expect(w.find('[data-test=refusal]').exists()).toBe(true)
    // 闸门审计说明由后端 gate_note 提供，真接口模式下不再有 mock 横幅
    expect(w.find('[data-test=gate-note]').text()).toContain('0.28')
  })

  it('J-2：拒答 chips 逐字来自 answer.suggestions（非前端常量）', async () => {
    stubAnswer({ ...ANSWER_REFUSED, suggestions: ['契约建议甲问题？', '契约建议乙问题？'] })
    const w = mount(AskView, { attachTo: document.body })
    await w.find('input').setValue('任意问题')
    await w.find('form').trigger('submit')
    await flushPromises()
    const chips = w.findAll('[data-test=suggest-chip]')
    expect(chips.map((c) => c.text())).toEqual(['契约建议甲问题？', '契约建议乙问题？'])
    for (const c of chips) expect(SAMPLE_QUESTIONS).not.toContain(c.text())
  })

  it('J-2：注册数无来源 → 文案不得出现「0 个来源」类错话', async () => {
    stubAnswer({ ...ANSWER_REFUSED, suggestions: ['甲？'] })
    const w = mount(AskView, { attachTo: document.body })
    await w.find('input').setValue('任意问题')
    await w.find('form').trigger('submit')
    await flushPromises()
    const zone = w.find('[data-test=refusal]').text()
    expect(zone).not.toMatch(/0\s*个来源|已登记的\s*0/)
    expect(zone).toContain('暂无记载')
  })
})
