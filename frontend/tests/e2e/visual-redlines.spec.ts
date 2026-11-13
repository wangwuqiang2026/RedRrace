// S8 e2e：C1/C3 红线 computed style 实测 + 768px 堆叠 + 无障碍基线。
// 断言写法照 docs/视觉验收-阶段零F.md §1.2 伪代码（visual-qa V1-a），不另起判定。
import { test, expect } from '@playwright/test'

async function goConflict(page: import('@playwright/test').Page) {
  await page.goto('/ask')
  await page.getByRole('button', { name: /不同记载|人数/ }).first().click()
  await expect(page.locator('[data-test=conflict]')).toBeVisible()
}

test('C1【红线】冲突两卡 computed style 六属性成对相等 + 禁用词零命中 + DOM 序=视觉序', async ({ page }) => {
  await goConflict(page)
  const cards = page.locator('[data-test=conflict] .source-card')
  await expect(cards).toHaveCount(2)
  for (const prop of ['fontSize', 'fontWeight', 'backgroundColor', 'borderColor', 'padding', 'width'] as const) {
    const a = await cards.nth(0).evaluate((e, p) => getComputedStyle(e)[p] as string, prop)
    const b = await cards.nth(1).evaluate((e, p) => getComputedStyle(e)[p] as string, prop)
    expect(a, `属性 ${prop} 不等：${a} vs ${b}`).toBe(b) // 任一不等即红线不通过
  }
  const txt = await page.locator('[data-test=conflict]').innerText()
  expect(txt).not.toMatch(/更可信|推荐|较新来源|仅供参考/)
  expect(txt).toContain('记载一')
  expect(txt).toContain('记载二')
  // DOM 顺序=视觉顺序
  // DOM 顺序=视觉顺序（I-3 修正：旧写法拿 boxes 的排序副本自比恒真）。
  // 按视口断单调性：并排=同 top 且 left 递增；堆叠=top 递增。
  const boxes = await cards.evaluateAll((els) =>
    els.map((e) => {
      const r = e.getBoundingClientRect()
      return { top: r.top, left: r.left, width: r.width, height: r.height }
    }),
  )
  const vw = page.viewportSize()!.width
  if (vw >= 768) {
    // 并排：左→右 DOM 序与 left 递增一致（卡序 S002→S003）
    expect(boxes[1].left, 'DOM 第 2 张应在第 1 张右侧（视觉序=DOM 序）').toBeGreaterThan(boxes[0].left)
    expect(Math.abs(boxes[1].top - boxes[0].top)).toBeLessThan(2)
  } else {
    expect(boxes[1].top, '堆叠时 DOM 第 2 张应在下方').toBeGreaterThan(boxes[0].top)
    expect(Math.abs(boxes[1].left - boxes[0].left)).toBeLessThan(2)
  }
})

test('I-7 配套：auto-fit 网格下 >2 条记载仍同排等宽（注入第三条 DOM，防孤行观感）', async ({ page }) => {
  test.skip(page.viewportSize()!.width < 768, '堆叠视口不适用并排等宽判据')
  await goConflict(page)
  await page.evaluate(() => {
    const grid = document.querySelector('[data-test=conflict] .conflict-grid')!
    const li = grid.querySelector('li.conflict-side')!.cloneNode(true) as HTMLElement
    li.querySelector('.source-card')!.setAttribute('data-source-id', 'S900')
    li.querySelector('.source-card')!.id = 'source-S900'
    grid.appendChild(li)
  })
  const widths = await page.locator('[data-test=conflict] .source-card').evaluateAll((els) =>
    els.map((e) => e.getBoundingClientRect().width),
  )
  expect(widths.length).toBe(3)
  expect(Math.max(...widths) - Math.min(...widths), '三卡同排应等宽（第三条不许掉成孤行）').toBeLessThan(2)
})

test('C3【红线】恒 source_id 升序（mock sides 乱序输入）+ 768px 纵向堆叠仍等权', async ({ page }) => {
  await goConflict(page)
  const ids = await page.locator('[data-test=conflict] [data-source-id]').evaluateAll((es) =>
    es.map((e) => (e as HTMLElement).dataset.sourceId as string),
  )
  // I-4 修正：断**具体期望序**（mock sides 现故意 S003 在前——删排序代码本断言即红），
  // 不用 ids==sort(ids) 自比较。
  expect(ids, 'DOM 序必须为 source_id 码点升序（S002→S003），而 mock sides 供数序为 S003→S002').toEqual(['S002', 'S003'])

  await page.setViewportSize({ width: 767, height: 900 })
  const cards = page.locator('[data-test=conflict] .source-card')
  const box0 = await cards.nth(0).boundingBox()
  const box1 = await cards.nth(1).boundingBox()
  expect(box0 && box1).toBeTruthy()
  // 纵向堆叠：卡 1 在卡 0 下方且左缘对齐（同宽等权）
  expect(box1!.y).toBeGreaterThan(box0!.y + box0!.height - 1)
  expect(Math.abs(box1!.x - box0!.x)).toBeLessThan(1)
  expect(Math.abs(box1!.width - box0!.width)).toBeLessThan(1)
  for (const prop of ['fontSize', 'fontWeight', 'backgroundColor', 'borderColor', 'padding', 'width'] as const) {
    const a = await cards.nth(0).evaluate((e, p) => getComputedStyle(e)[p] as string, prop)
    const b = await cards.nth(1).evaluate((e, p) => getComputedStyle(e)[p] as string, prop)
    expect(a, `堆叠后 ${prop} 不等`).toBe(b)
  }
})

test('B5【红线】拒答区：底色=--paper-muted 解析值、文字=--refusal-ink、无 role=alert、无报错图标、禁词零命中', async ({ page }) => {
  await page.goto('/ask')
  await page.getByRole('button', { name: /飞夺泸定桥/ }).click()
  const zone = page.locator('[data-test=refusal]')
  await expect(zone).toBeVisible()
  const bg = await zone.evaluate((e) => getComputedStyle(e as HTMLElement).backgroundColor)
  expect(bg).toBe('rgb(241, 241, 239)') // --paper-muted
  const color = await zone.locator('p').first().evaluate((e) => getComputedStyle(e as HTMLElement).color)
  expect(color).toBe('rgb(51, 82, 107)') // --refusal-ink
  await expect(zone.locator('[role=alert]')).toHaveCount(0)
  await expect(zone.locator('svg[data-icon=alert-triangle], svg[data-icon=x-circle]')).toHaveCount(0)
  expect(await zone.innerText()).not.toMatch(/错误|失败|异常|无法处理|出错/)
  expect(await zone.innerText()).toContain('仅参考，不构成对该问题的回答')
})

test('D4 封闭集 e2e：no_evidence 场景两类句子不互换、无错误红（compliance-docs 实测缺口补测）', async ({ page }) => {
  await page.goto('/ask')
  await page.getByRole('button', { name: /可用记载/ }).click()
  const zone = page.locator('[data-test=refusal]')
  await expect(zone).toBeVisible()
  const txt = await zone.innerText()
  expect(txt).toContain('这个问题暂时找不到可用记载')
  expect(txt).toContain('已登记的来源中找不到可支持的记载，为避免编造，不作回答')
  expect(txt).not.toContain('当前知识库未收录')
  const color = await zone.locator('p').first().evaluate((e) => getComputedStyle(e as HTMLElement).color)
  expect(color).toBe('rgb(51, 82, 107)') // 仍 --refusal-ink，不是错误红
})

test('A2 自动化子集：夹具答案每句末有可聚焦 sup 且锚点指向存在卡片（B3/B4）', async ({ page }) => {
  await page.goto('/ask')
  await page.getByRole('button', { name: /郴州/ }).first().click()
  const sups = page.locator('.answer-text sup a[data-test=cite-ref]')
  await expect(sups).toHaveCount(2)
  for (const sup of await sups.all()) {
    const href = await sup.getAttribute('href')
    await expect(page.locator(href!)).toHaveCount(1)
    await expect(sup).toHaveAccessibleName(/出处 \d：/)
  }
  // 键盘 Enter 激活：滚动定位 + 可见高亮（B4）。M-1 修复后闪烁动画必须真实作用于样式——
  // 只加类不算「可见高亮」，断言计算后的 animation-name。
  await sups.first().focus()
  await page.keyboard.press('Enter')
  const flash = page.locator('#source-S001.cite-flash, #source-S002.cite-flash').first()
  await expect(flash).toBeAttached()
  const anim = await flash.evaluate((e) => getComputedStyle(e as HTMLElement).animationName)
  expect(anim, '.cite-flash 无动画定义=高亮不可见（M-1）').toBe('cite-flash')
})

test('A6 键盘遍历：skip-link 是第一站，全交互元素焦点环 ≥2px 非 outline:none', async ({ page }) => {
  await page.goto('/ask')
  await page.keyboard.press('Tab')
  const focus = await page.evaluate(() => ({
    cls: document.activeElement?.className,
    text: document.activeElement?.textContent ?? '',
  }))
  expect(String(focus.cls)).toContain('skip-link')
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press('Tab')
    const style = await page.evaluate(() => {
      const s = getComputedStyle(document.activeElement as Element)
      return { outlineWidth: s.outlineWidth, outlineStyle: s.outlineStyle }
    })
    if (style.outlineStyle !== 'none') {
      expect(parseFloat(style.outlineWidth), '焦点环宽度').toBeGreaterThanOrEqual(2)
    }
  }
})
