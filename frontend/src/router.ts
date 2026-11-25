// All final routes registered up front; later phases replace view files only.
// The global guard is load-bearing on the Vite dev server (which serves the
// shell for every path) and after client-side logout: it reads /api/auth/me
// (200 even unauthenticated / during first boot) and enforces the same gating
// the server middleware does for prod deep links.
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { fetchMe } from './stores/auth'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'dashboard',
    component: () => import('./views/DashboardView.vue'),
    meta: { title: '概览' },
  },
  {
    path: '/pipeline',
    name: 'pipeline',
    component: () => import('./views/PipelineView.vue'),
    meta: { title: '处理流程' },
  },
  {
    path: '/review',
    name: 'review',
    component: () => import('./views/ReviewView.vue'),
    meta: { title: '人脸审核' },
  },
  {
    path: '/inspect/:space/:photoId',
    name: 'inspect-photo',
    component: () => import('./views/InspectView.vue'),
    meta: { title: '照片检视' },
  },
  {
    path: '/inspect',
    name: 'inspect',
    component: () => import('./views/InspectView.vue'),
    meta: { title: '照片检视' },
  },
  {
    path: '/apply',
    name: 'apply',
    component: () => import('./views/ApplyView.vue'),
    meta: { title: '写回群晖' },
  },
  {
    path: '/utilities',
    name: 'utilities',
    component: () => import('./views/UtilitiesView.vue'),
    meta: { title: '实用工具' },
  },
  {
    path: '/schedules',
    name: 'schedules',
    component: () => import('./views/SchedulesView.vue'),
    meta: { title: '定时任务' },
  },
  {
    path: '/stats',
    name: 'stats',
    component: () => import('./views/StatsView.vue'),
    meta: { title: '数据统计' },
  },
  {
    path: '/maintenance',
    name: 'maintenance',
    component: () => import('./views/MaintenanceView.vue'),
    meta: { title: '维护清理' },
  },
  {
    path: '/settings',
    name: 'settings',
    component: () => import('./views/SettingsView.vue'),
    meta: { title: '系统设置' },
  },
  {
    path: '/about',
    name: 'about',
    component: () => import('./views/AboutView.vue'),
    meta: { title: '关于' },
  },
  {
    path: '/jobs/:id',
    name: 'job',
    component: () => import('./views/JobView.vue'),
    meta: { title: '任务日志' },
  },
  {
    path: '/setup',
    name: 'setup',
    component: () => import('./views/SetupView.vue'),
    meta: { title: '初始化向导', bare: true },
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('./views/LoginView.vue'),
    meta: { title: '登录', bare: true },
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  let me
  try {
    me = await fetchMe()
  } catch {
    // /api/auth/me should always answer 200; on a hard network failure fall back
    // to the login screen rather than rendering chrome we cannot authorize.
    return to.name === 'login' ? true : { name: 'login', query: { next: to.fullPath } }
  }

  if (me.first_boot) {
    return to.name === 'setup' ? true : { name: 'setup' }
  }
  if (!me.authenticated) {
    return to.name === 'login' ? true : { name: 'login', query: { next: to.fullPath } }
  }
  // Authenticated: keep users out of the login shell. /setup stays reachable —
  // the old GET /setup page was a normal authenticated route too, so re-running
  // the wizard while signed in must keep working (its account step self-skips).
  if (to.name === 'login') {
    return { path: '/' }
  }
  return true
})

router.afterEach((to) => {
  const t = (to.meta.title as string | undefined) ?? 'Synopticon'
  document.title = `${t} · Synopticon`
})

export default router
