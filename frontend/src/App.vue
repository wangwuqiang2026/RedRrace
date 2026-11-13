<script setup lang="ts">
// App 壳：顶栏（站点标识 + 七页导航）→ 主内容 → 页脚（合规摘要）。
// 依据 docs/设计规范.md §5 通用结构：顶栏标识定稿 = RedTrace + 中文副题（与选题书标题逐字一致），
// 顶栏高 56px，深红仅用于 logo 块与当前导航项标识条（3px 下划线 + 字重 500，不单靠颜色）。
import { RouterLink, RouterView } from 'vue-router'
import { routes } from './router'

const navItems = routes.flatMap((r) =>
  r.meta?.nav ? [{ path: r.path, label: String(r.meta.nav) }] : [],
)
</script>

<template>
  <a class="skip-link" href="#main">跳到主内容</a>
  <header class="site-header">
    <div class="brand">
      <span class="brand-name">RedTrace</span>
      <span class="brand-sub">红色文化知识库与可溯源问答系统</span>
    </div>
    <nav class="site-nav" aria-label="主导航">
      <RouterLink v-for="item in navItems" :key="item.path" :to="item.path">
        {{ item.label }}
      </RouterLink>
    </nav>
  </header>
  <main id="main">
    <RouterView />
  </main>
  <footer class="site-footer">
    <p>
      本系统依据已登记来源回答，界面仅展示逐字引文片段与出处；内容遵循《合规与引用政策》。
      引用编号可回链到对应出处卡，出处以核验页为准。
    </p>
  </footer>
</template>

<style scoped>
.site-header {
  position: sticky;
  top: 0;
  z-index: var(--z-header);
  height: var(--header-height);
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: 0 var(--space-6);
  background: var(--paper-card);
  border-bottom: 1px solid var(--line-border);
}
.brand {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex-shrink: 0;
}
.brand-name {
  background: var(--brand-red);
  color: var(--ink-inverse);
  font-weight: var(--fw-bold);
  font-size: var(--text-h2);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-1);
}
.brand-sub {
  color: var(--cite-grey);
  font-size: var(--text-meta);
}
.site-nav {
  display: flex;
  gap: var(--space-4);
  overflow-x: auto;
}
.site-nav a {
  color: var(--ink);
  text-decoration: none;
  font-size: var(--text-meta);
  padding: var(--space-2) 0;
  white-space: nowrap;
}
.site-nav a:hover {
  text-decoration: underline;
}
/* 当前导航项：深红下划线 + 字重 500 + aria-current（R4 三通道） */
.site-nav a[aria-current='page'] {
  font-weight: var(--fw-medium);
  box-shadow: inset 0 -3px 0 var(--brand-red);
}
main {
  max-width: var(--container-width);
  margin: 0 auto;
  padding: var(--space-6);
  min-height: 60vh;
}
.site-footer {
  max-width: var(--container-width);
  margin: 0 auto;
  padding: var(--space-6);
  border-top: 1px solid var(--line-border);
  color: var(--cite-grey);
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
}
@media (max-width: 767px) {
  .site-header {
    flex-wrap: wrap;
    height: auto;
    padding: var(--space-2) var(--space-4);
  }
  .brand-sub {
    display: none;
  }
}
</style>
