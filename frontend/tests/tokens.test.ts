// S3 tokens.css 测试：色值必须与设计规范逐字一致，对比度用 WCAG 公式现场复算。
// 依据：docs/设计规范.md §3.1–§3.4（精确取值来源），不允许发明新值。
import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { resolveToken, tokenEntries, contrast } from '../src/lib/css-audit'

// vitest 的 cwd 是 frontend/；jsdom 环境下 import.meta.url 不是 file scheme，故用 cwd 解析。
const css = readFileSync(resolve('src/styles/tokens.css'), 'utf8')

// tokenEntries/resolveToken（层叠取末值 + 重复劫持必炸）实现于 tests/lib/css-audit.ts，
// 与 visual-qa v1-mutants 回归脚本同一份代码，避免双实现漂移（I-2 修复）。
function token(name: string): string {
  return resolveToken(css, name)
}

// 对比度公式（WCAG 2.x，规范 §3.4）复用 lib 实现
// 与规范表值比对（规范保留 2 位小数，容差 0.01）
function expectRatio(fg: string, bg: string, spec: number) {
  const got = contrast(fg, bg)
  expect(Math.abs(got - spec), `${fg} on ${bg} 实测 ${got.toFixed(2)}，规范 §3.4 为 ${spec}`).toBeLessThanOrEqual(0.01)
  return got
}

describe('tokens.css 精确取值（设计规范 §3.1–§3.3）', () => {
  it('中性基底逐字一致', () => {
    expect(token('paper-page')).toBe('#FAFAF9')
    expect(token('paper-card')).toBe('#FFFFFF')
    expect(token('paper-muted')).toBe('#F1F1EF')
    expect(token('ink')).toBe('#1F2430')
    expect(token('ink-inverse')).toBe('#FFFFFF')
    expect(token('cite-grey')).toBe('#475569')
    expect(token('line-border')).toBe('#E3E1DC')
  })

  it('品牌红三值逐字一致', () => {
    expect(token('brand-red')).toBe('#8E2430')
    expect(token('brand-red-deep')).toBe('#7A1E28')
    expect(token('brand-red-tint')).toBe('#F8EEEC')
  })

  it('语义色与链接蓝逐字一致', () => {
    expect(token('link-blue')).toBe('#1E4FA3')
    expect(token('disputed')).toBe('#8A5300')
    expect(token('disputed-bg')).toBe('#FAF0DC')
    expect(token('pass-green')).toBe('#166534')
    expect(token('pass-green-bg')).toBe('#EAF2EC')
    expect(token('revise')).toBe('#92400E')
    expect(token('revise-bg')).toBe('#FAF0DC')
    expect(token('refusal-ink')).toBe('#33526B')
    expect(token('error-red')).toBe('#A02020')
    expect(token('error-red-bg')).toBe('#F8E8E8')
    // 注记（M-2 同步修订版口径）：`--pending-line`(#A9824A) 已按规范 F4 登记于 §3.3，
    // 壳阶段无使用场景不落 tokens；阶段五时间轴「年代待考」区接入时再添加（仅图形线，禁作文字前景）。
  })

  it('拒答底色必须复用 --paper-muted（R3：中性底而非彩色底）', () => {
    expect(token('refusal-bg')).toBe('var(--paper-muted)')
  })

  it('字号阶梯与行高取自 §4.2', () => {
    expect(token('text-display')).toBe('32px')
    expect(token('text-h1')).toBe('24px')
    expect(token('text-h2')).toBe('18px')
    expect(token('text-body')).toBe('16px') // 正文最小值 16px（High 级规则）
    expect(token('text-meta')).toBe('14px')
    expect(token('text-caption')).toBe('12px')
    expect(token('line-height-body')).toBe('1.75') // 中文正文行高取 1.5–1.75 上限
  })

  it('间距/容器/顶栏取自 §4.3 与 §5', () => {
    expect(token('space-1')).toBe('4px')
    expect(token('container-width')).toBe('1080px')
    expect(token('header-height')).toBe('56px')
  })

  it('字体栈为系统回退链，禁止 Web Font CDN（§4.1 加载策略 + 清单 J2）', () => {
    expect(css).not.toMatch(/fonts\.googleapis|fonts\.gstatic|@font-face|url\(https?:/)
    expect(token('font-serif')).toMatch(/SimSun|Songti/)
    expect(token('font-sans')).toMatch(/Microsoft YaHei|PingFang/)
    expect(token('font-mono')).toMatch(/Consolas|JetBrains Mono/)
  })
})

describe('对比度复算与规范 §3.4 表一致', () => {
  it('B1：白字/品牌红 8.59:1（AA+AAA ≥7）', () => {
    expectRatio('#FFFFFF', token('brand-red'), 8.59)
  })
  it('B3：正文墨/页面底 14.86:1', () => {
    expectRatio(token('ink'), token('paper-page'), 14.86)
  })
  it('B4：正文墨/卡片白 15.52:1', () => {
    expectRatio(token('ink'), token('paper-card'), 15.52)
  })
  it('C1：引用灰/卡片白 7.58:1', () => {
    expectRatio(token('cite-grey'), token('paper-card'), 7.58)
  })
  it('C2：引用灰/页面底 7.26:1', () => {
    expectRatio(token('cite-grey'), token('paper-page'), 7.26)
  })
  it('C3：引用灰/paper-muted 6.70:1', () => {
    expectRatio(token('cite-grey'), token('paper-muted'), 6.7)
  })
  it('L1：链接蓝/卡片白 7.77:1', () => {
    expectRatio(token('link-blue'), token('paper-card'), 7.77)
  })
  it('S1：存疑褐/白 6.33:1；S2：存疑褐/浅琥珀 5.59:1', () => {
    expectRatio(token('disputed'), '#FFFFFF', 6.33)
    expectRatio(token('disputed'), token('disputed-bg'), 5.59)
  })
  it('G1：通过绿/浅绿底 6.25:1', () => {
    expectRatio(token('pass-green'), token('pass-green-bg'), 6.25)
  })
  it('V1：需修改橙褐/白 7.09:1', () => {
    expectRatio(token('revise'), '#FFFFFF', 7.09)
  })
  it('F1：拒答蓝灰/paper-muted 7.25:1', () => {
    expectRatio(token('refusal-ink'), token('paper-muted'), 7.25)
  })
  it('X1：冲突标题品牌红/#F8EEEC 7.54:1；X2：墨/#F8EEEC 13.62:1', () => {
    expectRatio(token('brand-red'), token('brand-red-tint'), 7.54)
    expectRatio(token('ink'), token('brand-red-tint'), 13.62)
  })
  it('E1：错误红/浅红底 6.50:1', () => {
    expectRatio(token('error-red'), token('error-red-bg'), 6.5)
  })
  it('D1：主轴线/页面底 8.22:1（≥3:1 图形线）', () => {
    expect(expectRatio(token('brand-red'), token('paper-page'), 8.22)).toBeGreaterThanOrEqual(3)
  })
  // D2 线（#A9824A）壳阶段不落 token，见上方注记，不在此复算。
  it('K1：焦点环链接蓝/卡片白 7.77:1（≥3:1）', () => {
    expect(expectRatio(token('link-blue'), token('paper-card'), 7.77)).toBeGreaterThanOrEqual(3)
  })

  it('反例复核：俗艳黄/大红 3.15:1 不达标（公式正确性交叉验证）', () => {
    expect(contrast('#FACC15', '#DC2626')).toBeCloseTo(3.15, 2)
    expect(contrast('#FACC15', '#DC2626')).toBeLessThan(4.5)
  })
  it('反例复核：#999999/白 2.85:1 不达标', () => {
    expect(contrast('#999999', '#FFFFFF')).toBeCloseTo(2.85, 2)
  })

  it('正文级配对全部 ≥4.5:1（清单 A3 的自动化子集）', () => {
    const bodyPairs: Array<[string, string]> = [
      [token('ink'), token('paper-page')],
      [token('ink'), token('paper-card')],
      [token('cite-grey'), token('paper-card')],
      [token('cite-grey'), token('paper-muted')],
      [token('link-blue'), token('paper-card')],
      [token('refusal-ink'), token('paper-muted')],
      [token('disputed'), token('disputed-bg')],
      [token('pass-green'), token('pass-green-bg')],
      [token('revise'), token('paper-card')],
      [token('error-red'), token('error-red-bg')],
      [token('brand-red'), token('brand-red-tint')],
    ]
    for (const [fg, bg] of bodyPairs) {
      expect(contrast(fg, bg), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('边框 #E3E1DC 对页面底仅 ≈1.25:1 → 被声明为纯装饰（§6.4，T7 装饰豁免）', () => {
    const c = contrast(token('line-border'), token('paper-page'))
    expect(c).toBeGreaterThan(1.2)
    expect(c).toBeLessThan(1.3)
  })
})

describe('I-2 层叠语义：同名重复定义不得逃逸', () => {
  const rogue = readFileSync(resolve('tests/fixtures/mutants/M6-dup-token.css'), 'utf8')

  it('对照证明旧实现漏检：首个匹配取到合法值 #1F2430（测试会绿）', () => {
    const firstWay = rogue.match(/--ink:\s*([^;]+);/)![1].trim()
    expect(firstWay).toBe('#1F2430')
  })

  it('新实现按浏览器生效值（末位）读取 → 得到劫持值 #BEEF00 并判失败', () => {
    expect(tokenEntries(rogue, 'ink')).toEqual(['#1F2430', '#BEEF00'])
    expect(() => resolveToken(rogue, 'ink')).toThrow(/重复定义/)
  })

  it('真实 tokens.css 中任何 token 至多一种取值（无重复劫持面）', () => {
    const names = [...css.matchAll(/--([a-z0-9-]+):/g)].map((m) => m[1])
    expect(names.length).toBeGreaterThan(20) // 防恒真
    for (const n of new Set(names)) {
      const all = tokenEntries(css, n)
      expect(new Set(all).size, `--${n} 出现 ${all.length} 次且取值不一致`).toBe(1)
    }
  })
})

describe('M-1 tint/琥珀族对比度线（规范修订版 §3.4 T1–T8，最低线 6.27）', () => {
  it('T1 引用灰/tint 6.65；T2 链接蓝/tint 6.82；T3 拒答蓝灰/tint 7.20', () => {
    expectRatio(token('cite-grey'), token('brand-red-tint'), 6.65)
    expectRatio(token('link-blue'), token('brand-red-tint'), 6.82)
    expectRatio(token('refusal-ink'), token('brand-red-tint'), 7.2)
  })

  it('T4 链接蓝/琥珀 6.87；T5 需修改/琥珀 6.27（本族最低线）；T8 正文墨/琥珀 13.72', () => {
    expectRatio(token('link-blue'), token('disputed-bg'), 6.87)
    expect(expectRatio(token('revise'), token('disputed-bg'), 6.27)).toBeGreaterThanOrEqual(4.5)
    expectRatio(token('ink'), token('disputed-bg'), 13.72)
  })

  it('T6 白字/hover 深红 10.27', () => {
    expectRatio(token('ink-inverse'), token('brand-red-deep'), 10.27)
  })

  it('T 族全部并入 AA 红线（≥4.5，F1 修订：AAA 只作增强目标）', () => {
    const tint = token('brand-red-tint')
    const amber = token('disputed-bg')
    for (const [fg, bg] of [
      [token('cite-grey'), tint],
      [token('link-blue'), tint],
      [token('refusal-ink'), tint],
      [token('link-blue'), amber],
      [token('revise'), amber],
      [token('ink'), amber],
    ]) {
      expect(contrast(fg, bg), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5)
    }
  })
})
