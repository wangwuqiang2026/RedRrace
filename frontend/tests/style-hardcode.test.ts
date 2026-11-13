// S3 红线自动化 + visual-qa V1 二轮 I-1 补强：
// 检测面与扫描集实现见 src/lib/css-audit.ts（生产侧 lib；vitest、%TEMP% v1-mutants 回归脚本、
// visual-qa 专项回归共用同一实现——批准 1）。
// 本文件保留「旧实现」复刻作对照断言：证明四类逃逸破法在旧面下漏检、在新面下被抓。
import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { relative, resolve } from 'node:path'
import { findHardcodedColors, collectScanTargets } from '../src/lib/css-audit'

/** 旧版检测（V1 实审判定存在漏检面，仅此处保留供对照）。 */
const HEX_ONLY_OLD = /#[0-9a-fA-F]{3,8}\b/g
function findHardcodedHexOld(file: string): string[] {
  const src = readFileSync(file, 'utf8')
  const text = file.endsWith('.vue')
    ? [...src.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]).join('\n')
    : src
  return text.match(HEX_ONLY_OLD) ?? []
}

const MUT = (name: string) => resolve('tests/fixtures/mutants', name)

describe('S3 硬编码色值检测（检测器非恒真）', () => {
  it('好样本不报：仅 var() 引用与新检测面无冲突', () => {
    expect(findHardcodedColors(resolve('tests/fixtures/GoodStyle.vue'))).toEqual([])
  })

  it('坏样本被报（基础 hex）', () => {
    expect(findHardcodedColors(resolve('tests/fixtures/BadStyle.vue')).length).toBeGreaterThan(0)
  })
})

describe('I-1 四类逃逸破法必须全部被抓（visual-qa V1 二轮）', () => {
  it('M1 模板内联 style / SVG fill 属性 / :style 绑定对象', () => {
    const hits = findHardcodedColors(MUT('M1-inline.vue'))
    expect(hits).toEqual(expect.arrayContaining(['#8E2430', '#166534', '#A02020']))
    // 对照：旧实现（只抽 <style> 块 + 仅 hex）确实漏掉这三处
    expect(findHardcodedHexOld(MUT('M1-inline.vue'))).toEqual([])
  })

  it('M2 rgb()/hsl() 函数式色、命名色 color:red、data-URI %23hex', () => {
    const hits = findHardcodedColors(MUT('M2-fncolor.vue'))
    expect(hits.length, `命中明细：${JSON.stringify(hits)}`).toBeGreaterThanOrEqual(4)
    expect(hits.join(' ')).toMatch(/rgb|hsl|%23|color: red/i)
    // 对照：旧实现对这四种写法全漏（无 #hex 可寻）
    expect(findHardcodedHexOld(MUT('M2-fncolor.vue'))).toEqual([])
  })

  it('M3 public/ 下样式文件必须进扫描集并能被抓到（I-5：新旧口径同树对照，不是拿不存在目录凑数）', () => {
    const fakeRoot = resolve('tests/fixtures/fake-project')
    const targets = collectScanTargets(fakeRoot)
    const rogue = targets.find((f) => /palette-rogue/.test(f))
    expect(rogue, '新扫描集必须收录 public/ 文件').toBeTruthy()
    expect(findHardcodedColors(rogue!).length).toBeGreaterThan(0)
    // 真对照：同一份目录树，旧口径（只走 src/）根本看不到这个文件——漏检是集合差异，不是正则差异
    const oldSet = targets.filter((f) => /[\\/]src[\\/]/.test(f))
    expect(oldSet, '旧口径（src-only）下 fake-project 应零收录').toEqual([])
    expect(targets.length).toBeGreaterThan(oldSet.length)
  })

  it('M4 新扫描集严格宽于旧扫描集（src 之外必须含 public/index.html）', () => {
    const all = collectScanTargets(resolve())
    expect(all.some((f) => /index\.html$/.test(f) || /[\\/]public[\\/]/.test(f))).toBe(true)
  })
})

describe('批准 1：审计 lib 落位与静态 import 链（防双实现假绿）', () => {
  it('实现唯一落点 src/lib/css-audit.ts，消费方全部静态 import 该路径，tests/lib 旧位置不得复活', () => {
    expect(existsSync(resolve('src/lib/css-audit.ts'))).toBe(true)
    expect(existsSync(resolve('tests/lib/css-audit.ts'))).toBe(false)
    for (const f of ['tests/style-hardcode.test.ts', 'tests/tokens.test.ts']) {
      expect(readFileSync(resolve(f), 'utf8'), `${f} 必须静态 import 生产侧 lib`).toMatch(
        /from\s+'(?:\.\.\/)+src\/lib\/css-audit'/,
      )
    }
  })

  // C-2 附带锁：src 扩展名已含 .ts → lib 自身（60+ 命名色清单）必须被排除；
  // 同时防「一刀切排除所有 .ts」把真实生产代码也放出去。
  it('lib 自身不参与扫描；src 其他 .ts 文件必须进扫描集', () => {
    const targets = collectScanTargets(resolve())
    expect(targets.some((f) => /src[\\/]lib[\\/]css-audit\.ts$/.test(f))).toBe(false)
    expect(targets.some((f) => /[\\/]src[\\/].*\.ts$/.test(f)), 'src 下其他 .ts 应进扫描集').toBe(true)
  })
})

describe('项目自身必须全绿', () => {
  it('src/、public/、index.html 全检测面零命中（tokens.css 除外）', () => {
    const projectRoot = resolve()
    const files = collectScanTargets(projectRoot).filter(
      (f) => !/[\\/]styles[\\/]tokens\.css$/.test(f),
    )
    expect(files.length, '应有待扫描文件').toBeGreaterThan(0)
    const offenders = files
      .map((f) => [relative(projectRoot, f), findHardcodedColors(f)] as const)
      .filter(([, hits]) => hits.length > 0)
    expect(offenders, `硬编码色值：${JSON.stringify(offenders)}`).toEqual([])
  })
})
