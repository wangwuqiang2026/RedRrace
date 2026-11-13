// S7 七页路由骨架测试：路由可达 + 空状态文案（接入阶段 + 线框说明），先红后绿。
// 依据：任务简报 S7；docs/设计规范.md §5.3–§5.8 各节线框描述。
import { describe, it, expect } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import App from '../src/App.vue'
import { router } from '../src/router'

const PHASE_TEXT: Record<string, string> = {
  '/ask': '', // 问答页壳另有内容，见 S6 测试
  '/cards': '阶段五',
  '/timeline': '阶段五',
  '/map': '阶段五',
  '/routes': '阶段六',
  '/lesson-pack': '阶段六',
  '/audit': '阶段七',
}

describe('七页路由骨架', () => {
  it.each(Object.keys(PHASE_TEXT))('路由 %s 可达', async (path) => {
    await router.push(path)
    await flushPromises()
    expect(router.currentRoute.value.path).toBe(path)
  })

  it('根路径 / 重定向到 /ask', async () => {
    await router.push('/')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/ask')
  })

  for (const [path, phase] of Object.entries(PHASE_TEXT)) {
    if (!phase) continue
    it(`${path} 空状态显示「将在${phase}接入」与最终形态线框说明，且无假图表`, async () => {
      await router.push(path)
      const w = mount(App, { global: { plugins: [router] } })
      await flushPromises()
      const main = w.find('#main')
      expect(main.exists()).toBe(true)
      expect(main.text()).toContain(phase)
      expect(main.text()).toContain('接入')
      expect(main.text()).toContain('线框') // 取自设计规范的未来形态说明
      // 壳阶段红线：不出现 ECharts / canvas 假图表
      expect(main.find('canvas').exists()).toBe(false)
      expect(main.html()).not.toMatch(/echarts/i)
    })
  }
})
