import { describe, it, expect, vi, afterEach } from 'vitest'
import { prefersReducedMotion, createReveal, createCounter, createStagger, createPathDraw, motionContext } from '../src/lib/motion'

describe('motion 工厂降级', () => {
  afterEach(() => vi.unstubAllGlobals())
  it('测试环境下所有工厂返回 null，不启动 GSAP', () => {
    const el = document.createElement('div')
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path')
    expect(createReveal(el)).toBeNull()
    expect(createStagger([el])).toBeNull()
    expect(createCounter(el, 42)).toBeNull()
    expect(createPathDraw(path)).toBeNull()
    expect(motionContext(el)).toBeNull()
  })
  it('prefersReducedMotion 读取 matchMedia', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: true }))
    expect(prefersReducedMotion()).toBe(true)
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false }))
    expect(prefersReducedMotion()).toBe(false)
  })
})
