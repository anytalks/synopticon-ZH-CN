<script setup lang="ts">
// App shell: sidebar + topbar + <router-view>, with the always-mounted
// ToastHost and ConfirmDialog. Routes with meta.bare (login, setup) render
// without the chrome. Topbar ports base.html.j2: nav toggle, running-job chip,
// theme menu, and the account menu (username + sign out).
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import router from './router'
import SidebarNav from './components/SidebarNav.vue'
import ToastHost from './components/ToastHost.vue'
import ConfirmDialog from './components/ConfirmDialog.vue'
import { useAuth } from './stores/auth'
import { useJobs } from './stores/jobs'
import { useTheme, type ThemeMode } from './composables/useTheme'
import { phaseLabel } from './composables/useJobStream'
import { jobLabel } from './utils/jobs'

const route = useRoute()
const { state: auth, logout } = useAuth()
const { state: jobs, startJobPolling, stopJobPolling } = useJobs()
const { setTheme } = useTheme()

const bare = computed(() => route.meta.bare === true)
const title = computed(() => (route.meta.title as string | undefined) ?? 'Synopticon')
const username = computed(() => auth.me?.username ?? null)
const avatar = computed(() => (username.value ?? '?').charAt(0).toUpperCase())

const themeOpen = ref(false)
const userOpen = ref(false)

// `同步图库 · 同步人脸数据 99%` — the chip is the only progress indication on pages
// that do not host a JobPanel, so it carries the phase and percentage the
// listing already provides rather than a bare "running".
const jobChipText = computed(() => {
  const j = jobs.running
  if (!j) return ''
  const label = jobLabel(j.name)
  if (j.state === 'queued') return `${label} 排队中`
  const p = j.progress
  if (!p?.phase) return `${label} 运行中`
  const phase = phaseLabel(p.phase)
  return p.pct === null ? `${label} · ${phase}` : `${label} · ${phase} ${p.pct}%`
})

function toggleTheme(): void {
  userOpen.value = false
  themeOpen.value = !themeOpen.value
}
function toggleUser(): void {
  themeOpen.value = false
  userOpen.value = !userOpen.value
}
function chooseTheme(m: ThemeMode): void {
  setTheme(m)
  themeOpen.value = false
}
function toggleNav(): void {
  document.body.classList.toggle('nav-open')
}
async function doLogout(): Promise<void> {
  userOpen.value = false
  await logout()
  void router.push({ name: 'login' })
}

function onDocClick(e: MouseEvent): void {
  if (!(e.target as HTMLElement).closest('.menu')) {
    themeOpen.value = false
    userOpen.value = false
  }
}
function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape') {
    themeOpen.value = false
    userOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
  startJobPolling()
})
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKeydown)
  stopJobPolling()
})
</script>

<template>
  <RouterView v-if="bare" />
  <template v-else>
    <a class="skip-link" href="#main">跳至正文内容</a>
    <div class="layout">
      <SidebarNav />
      <div class="content">
        <header class="topbar" role="banner">
          <button
            class="icon-btn nav-toggle"
            type="button"
            aria-label="展开或收起导航栏"
            @click="toggleNav"
          >
            &#9776;
          </button>
          <h1 class="topbar-title">{{ title }}</h1>
          <div class="topbar-spacer"></div>
          <RouterLink
            v-if="jobs.running"
            class="job-indicator"
            :to="`/jobs/${jobs.running.id}`"
            aria-live="polite"
          >
            <span class="spinner" aria-hidden="true"></span>
            <span>{{ jobChipText }}</span>
          </RouterLink>
          <div class="menu" :class="{ open: themeOpen }" id="theme-menu">
            <button
              class="icon-btn"
              type="button"
              aria-haspopup="true"
              :aria-expanded="themeOpen"
              title="外观主题"
              aria-label="外观主题"
              @click="toggleTheme"
            >
              &#9681;
            </button>
            <div class="menu-panel" role="menu">
              <button role="menuitemradio" @click="chooseTheme('auto')">跟随系统</button>
              <button role="menuitemradio" @click="chooseTheme('light')">浅色</button>
              <button role="menuitemradio" @click="chooseTheme('dark')">深色</button>
            </div>
          </div>
          <div class="menu" :class="{ open: userOpen }" id="user-menu">
            <button
              class="icon-btn"
              type="button"
              aria-haspopup="true"
              :aria-expanded="userOpen"
              aria-label="账号菜单"
              @click="toggleUser"
            >
              {{ avatar }}
            </button>
            <div class="menu-panel" role="menu">
              <div class="menu-label">{{ username ?? '未登录' }}</div>
              <RouterLink role="menuitem" to="/settings" @click="userOpen = false"
                >系统设置</RouterLink
              >
              <button type="button" role="menuitem" @click="doLogout">退出登录</button>
            </div>
          </div>
        </header>
        <main id="main" class="main" role="main" tabindex="-1">
          <RouterView />
        </main>
      </div>
    </div>
  </template>
  <ToastHost />
  <ConfirmDialog />
</template>
