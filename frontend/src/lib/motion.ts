// RedTrace 动效基础设施 —— GSAP 工厂封装与测试环境降级。
// 后续所有页面只依赖本文件导出的稳定签名，不直接 import gsap/ScrollTrigger。
import gsap from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import { MotionPathPlugin } from 'gsap/MotionPathPlugin'

gsap.registerPlugin(ScrollTrigger, MotionPathPlugin)

// vitest/jsdom 没有真实布局，ScrollTrigger 会挂；测试环境统一 no-op。
// 服务端渲染（无 window）时同样禁用。
const DISABLED = import.meta.env.MODE === 'test' || typeof window === 'undefined'

export function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
    : false
}

/** 元素默认在 CSS 中可见；动画只做 gsap.from()，reduced-motion 下内容完整显示。 */
export function createReveal(el: Element, opts?: { y?: number; delay?: number }): gsap.core.Tween | null {
  if (DISABLED || prefersReducedMotion()) return null
  return gsap.from(el, {
    opacity: 0,
    y: opts?.y ?? 24,
    delay: opts?.delay ?? 0,
    duration: 0.8,
    ease: 'power2.out',
  })
}

/** 列表/网格的错峰入场。 */
export function createStagger(els: Element[], opts?: { y?: number; stagger?: number }): gsap.core.Tween | null {
  if (DISABLED || prefersReducedMotion()) return null
  return gsap.from(els, {
    opacity: 0,
    y: opts?.y ?? 20,
    stagger: opts?.stagger ?? 0.1,
    duration: 0.7,
    ease: 'power2.out',
  })
}

/** 数字滚动：补间普通对象，逐帧写入 textContent。 */
export function createCounter(el: Element, to: number, opts?: { duration?: number; suffix?: string }): gsap.core.Tween | null {
  if (DISABLED || prefersReducedMotion()) return null
  const obj = { v: 0 }
  return gsap.to(obj, {
    v: to,
    duration: opts?.duration ?? 1.2,
    ease: 'power2.out',
    onUpdate: () => {
      el.textContent = Math.round(obj.v) + (opts?.suffix ?? '')
    },
  })
}

/** SVG 路径描绘：按真实路径长度设置 dash，再随滚动把 offset 补间到 0。 */
export function createPathDraw(el: SVGPathElement, opts?: { trigger?: Element }): gsap.core.Tween | null {
  if (DISABLED || prefersReducedMotion()) return null
  const length = el.getTotalLength()
  el.style.strokeDasharray = String(length)
  el.style.strokeDashoffset = String(length)
  return gsap.to(el, {
    strokeDashoffset: 0,
    duration: 1,
    ease: 'none',
    scrollTrigger: {
      trigger: opts?.trigger ?? el,
      start: 'top 85%',
      end: 'center 40%',
      scrub: 1,
    },
  })
}

/** 动效作用域：调用方可 .revert() 统一清理本作用域内的 tween/ScrollTrigger。 */
export function motionContext(scope: Element): gsap.Context | null {
  return DISABLED ? null : gsap.context(() => {}, scope)
}
