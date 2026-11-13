// Vitest 全局 setup：jsdom 缺失的浏览器 API 在此补齐，供各测试共用。
// matchMedia：ConflictPair 窄屏堆叠等响应式逻辑在 jsdom 下需要它（默认 ≥768px 桌面态）。
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false, // 默认按桌面视口处理；窄屏分支由 Playwright 真实视口覆盖
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
})

// CitationMark 的滚动定位在 jsdom 无实现：补 noop，让闪烁 class 逻辑照常执行。
if (typeof Element.prototype.scrollIntoView !== 'function') {
  Element.prototype.scrollIntoView = (_arg?: boolean | ScrollIntoViewOptions) => {}
}
