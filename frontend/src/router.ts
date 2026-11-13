// 七页路由（简报 S7）。三视图/图表类页面按设计规范 §7 用路由级动态导入做代码分包；
// 壳阶段不引入任何图表库，避免阶段五换库返工。
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

export const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/ask' },
  {
    path: '/ask',
    name: 'ask',
    meta: { nav: '问答' },
    component: () => import('./views/AskView.vue'),
  },
  {
    path: '/cards',
    name: 'cards',
    meta: { nav: '卡片库' },
    component: () => import('./views/CardsView.vue'),
  },
  {
    path: '/timeline',
    name: 'timeline',
    meta: { nav: '时间轴' },
    component: () => import('./views/TimelineView.vue'),
  },
  {
    path: '/map',
    name: 'map',
    meta: { nav: '地图' },
    component: () => import('./views/MapView.vue'),
  },
  {
    path: '/routes',
    name: 'routes',
    meta: { nav: '研学路线' },
    component: () => import('./views/RoutesView.vue'),
  },
  {
    path: '/lesson-pack',
    name: 'lesson-pack',
    meta: { nav: '素材包' },
    component: () => import('./views/LessonView.vue'),
  },
  {
    path: '/audit',
    name: 'audit',
    meta: { nav: '审核台' },
    component: () => import('./views/AuditView.vue'),
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})
