<script setup lang="ts">
// App 壳：顶栏（站点标识 + 七页导航）→ 主内容 → 页脚（合规摘要）。
// 深色玻璃态改造：导航项依次浮入由 GSAP 工厂驱动，motionContext 统一管理，测试环境自动降级为 null。
// 结构契约（skip-link / header.site-header / main#main / footer.site-footer / RouterLink v-for）保持不变。
import { onMounted, onUnmounted, ref } from 'vue'
import { RouterLink, RouterView } from 'vue-router'
import { routes } from './router'
import { createStagger, motionContext } from './lib/motion'

const navItems = routes.flatMap((r) =>
  r.meta?.nav ? [{ path: r.path, label: String(r.meta.nav) }] : [],
)

const navRef = ref<HTMLElement | null>(null)
let ctx: ReturnType<typeof motionContext> = null

onMounted(() => {
  const nav = navRef.value
  if (!nav) return
  ctx = motionContext(nav)
  if (!ctx) return
  const links = Array.from(nav.querySelectorAll('a'))
  if (links.length) {
    ctx.add(() => {
      createStagger(links, { y: 16, stagger: 0.06 })
    })
  }
})

onUnmounted(() => {
  ctx?.revert()
  ctx = null
})
</script>

<template>
  <a class="skip-link" href="#main">跳到主内容</a>
  <header class="site-header">
    <div class="brand">
      <span class="brand-name">RedTrace</span>
      <span class="brand-sub">红色文化知识库与可溯源问答系统</span>
    </div>
    <nav ref="navRef" class="site-nav" aria-label="主导航">
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
  min-height: var(--header-height);
  display: flex;
  align-items: center;
  gap: var(--space-6);
  padding: 0 var(--space-6);
  background: var(--dm-bg-glass);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border-bottom: 1px solid var(--dm-line);
}
.brand {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  flex-shrink: 0;
}
.brand-name {
  background: linear-gradient(135deg, var(--dm-red), var(--dm-red-dim));
  color: var(--dm-ink);
  font-family: var(--dm-font-display);
  font-weight: var(--fw-bold);
  font-size: var(--text-h2);
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-1);
  text-shadow: 0 0 12px var(--dm-glow-red);
  box-shadow: 0 0 16px var(--dm-glow-red);
}
.brand-sub {
  color: var(--dm-ink-dim);
  font-size: var(--text-meta);
}
.site-nav {
  display: flex;
  gap: var(--space-4);
  overflow-x: auto;
  scrollbar-width: none;
}
.site-nav::-webkit-scrollbar {
  display: none;
}
.site-nav a {
  color: var(--dm-ink-dim);
  text-decoration: none;
  font-size: var(--text-meta);
  padding: var(--space-2) 0;
  white-space: nowrap;
  transition: color 0.25s ease, box-shadow 0.25s ease;
}
.site-nav a:hover {
  color: var(--dm-ink);
}
/* 当前导航项：朱砂红底部光条 + 字重 500 + aria-current（不单靠颜色） */
.site-nav a[aria-current='page'] {
  color: var(--dm-ink);
  font-weight: var(--fw-medium);
  box-shadow: inset 0 -3px 0 var(--dm-red);
}
main {
  max-width: var(--container-width);
  margin: 0 auto;
  padding: var(--space-6);
  min-height: 60vh;
  color: var(--dm-ink);
}
.site-footer {
  max-width: var(--container-width);
  margin: 0 auto;
  padding: var(--space-6);
  border-top: 1px solid var(--dm-line);
  color: var(--dm-ink-dim);
  font-size: var(--text-meta);
  line-height: var(--line-height-meta);
}

@media (max-width: 1023px) {
  .site-header {
    gap: var(--space-4);
    padding: 0 var(--space-4);
  }
  .brand-sub {
    display: none;
  }
}
@media (max-width: 767px) {
  .site-header {
    flex-wrap: wrap;
    height: auto;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-4);
  }
  .brand-name {
    font-size: var(--text-body);
  }
  .site-nav {
    width: 100%;
    gap: var(--space-3);
  }
  main {
    padding: var(--space-4);
  }
  .site-footer {
    padding: var(--space-4);
  }
}
</style>
