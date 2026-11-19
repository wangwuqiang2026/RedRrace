// 七页路由测试：路由可达 + / 重定向 + 新页面标题断言。
// 标题逐字取自 motion-makeover task-2-brief；后续 Task 4-6 实现对应页面后启用标题断言。
import { describe, it, expect } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import App from '../src/App.vue'
import { router } from '../src/router'

const TITLES: Record<string, string> = {
  '/ask': '', // 问答页另有测试，见 ask-view.test.ts
  '/cards': '来源档案库',
  '/timeline': '历史时间轴',
  '/map': '事件地理分布',
  '/routes': '重走长征路',
  '/lesson-pack': '研学素材包',
  '/audit': '来源审核台',
}

describe('七页路由骨架', () => {
  it.each(Object.keys(TITLES))('路由 %s 可达', async (path) => {
    await router.push(path)
    await flushPromises()
    expect(router.currentRoute.value.path).toBe(path)
  })

  it('根路径 / 重定向到 /ask', async () => {
    await router.push('/')
    await flushPromises()
    expect(router.currentRoute.value.path).toBe('/ask')
  })

  // Task 4 完成 /cards、/timeline、/map，Task 5 完成 /routes，
  // Task 6 完成 /lesson-pack、/audit——6 条标题断言全部启用。
  const ENABLED = new Set(['/cards', '/timeline', '/map', '/routes', '/lesson-pack', '/audit'])
  for (const [path, title] of Object.entries(TITLES)) {
    if (!title) continue
    const run = ENABLED.has(path) ? it : it.skip
    run(`${path} 显示新页面标题「${title}」`, async () => {
      await router.push(path)
      const w = mount(App, { global: { plugins: [router] } })
      await flushPromises()
      expect(w.find('#main').text()).toContain(title)
    })
  }
})
