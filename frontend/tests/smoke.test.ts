// S2 脚手架冒烟测试：App 壳（顶栏/导航/skip-link/页脚）必须先红后绿。
// 依据：docs/设计规范.md §5 通用结构（顶栏标识定稿）、§6.1（skip-link）。
import { describe, it, expect, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import App from '../src/App.vue'
import { router } from '../src/router'

async function mountApp() {
  const wrapper = mount(App, { global: { plugins: [router] } })
  await router.isReady()
  await flushPromises()
  return wrapper
}

describe('App 壳（阶段零F 骨架）', () => {
  beforeEach(async () => {
    await router.push('/')
    await flushPromises()
  })

  it('顶栏含 RedTrace 主标识与中文副题（与选题书标题逐字一致）', async () => {
    const w = await mountApp()
    const header = w.find('header')
    expect(header.exists()).toBe(true)
    expect(header.text()).toContain('RedTrace')
    expect(header.text()).toContain('红色文化知识库与可溯源问答系统')
  })

  it('提供跳到主内容的 skip-link（设计规范 §6.1）', async () => {
    const w = await mountApp()
    const skip = w.find('a.skip-link')
    expect(skip.exists()).toBe(true)
    expect(skip.attributes('href')).toBe('#main')
    expect(w.find('#main').exists()).toBe(true)
  })

  it('导航为七页且当前项带 aria-current="page"', async () => {
    await router.push('/ask')
    const w = await mountApp()
    const links = w.findAll('nav a')
    expect(links.length).toBe(7)
    const current = links.filter((l) => l.attributes('aria-current') === 'page')
    expect(current.length).toBe(1)
    expect(current[0].text()).toContain('问答')
  })

  it('页脚含合规说明摘要（指向合规与引用政策的中文说明）', async () => {
    const w = await mountApp()
    const footer = w.find('footer')
    expect(footer.exists()).toBe(true)
    expect(footer.text()).toContain('合规')
  })

  it('界面除例外白名单外无连续英文词（清单 A4 的壳阶段自动化子集）', async () => {
    const w = await mountApp()
    // 例外白名单：RedTrace 专名；其余可见文案不应出现连续英文单词
    const text = w.text()
    const bad = text.match(/[A-Za-z]{2,}(?:\s+[A-Za-z]{2,})+/g)
    expect(bad).toBeNull()
  })
})
