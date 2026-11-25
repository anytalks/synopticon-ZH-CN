<script setup lang="ts">
// About page: what this build is, and the environment facts a bug report needs.
// Everything comes from GET /api/about (import-light on the server side) plus
// the cached /api/auth/me version so the header renders before the fetch lands.
import { ref, computed, onMounted } from 'vue'
import { getJSON } from '../api/client'
import type { AboutInfo } from '../api/types'
import { useAuth } from '../stores/auth'

const REPO = 'https://github.com/fdebijl/synopticon'

const info = ref<AboutInfo | null>(null)
const loaded = ref(false)
const copied = ref(false)
const { state: auth } = useAuth()

const version = computed(() => info.value?.version ?? auth.me?.version ?? '')
const repo = computed(() => info.value?.repo_url || REPO)

const packages = computed(() =>
  Object.entries(info.value?.packages ?? {}).filter(([, v]) => v !== null),
)

interface Row {
  label: string
  value: string
  mono?: boolean
}

const rows = computed<Row[]>(() => {
  const i = info.value
  if (!i) return []
  const cores =
    `${i.cpu.available_cores} 可用核 · ${i.cpu.physical_cores} 物理核` +
    (i.cpu.cgroup_quota != null ? ` · cgroup 配额 ${i.cpu.cgroup_quota}` : '')
  return [
    { label: '软件版本', value: 'v' + i.version },
    {
      label: '处理流程版本',
      value: i.pipeline_version ?? (i.models_ready ? '未知' : '缺少模型权重'),
      mono: i.pipeline_version != null,
    },
    { label: 'Python 版本', value: i.python },
    { label: '运行平台', value: i.platform },
    { label: '处理器 (CPU)', value: cores },
    { label: '数据目录', value: i.paths.data_dir, mono: true },
    { label: '模型目录', value: i.paths.models_dir, mono: true },
    { label: '数据库路径', value: i.paths.db_path, mono: true },
  ]
})

// One paste-ready block for GitHub issues — the whole reason the environment
// facts are on a page instead of only in `synopticon hwinfo`.
const report = computed(() => {
  const i = info.value
  if (!i) return ''
  const lines = rows.value.map((r) => `- ${r.label}: ${r.value}`)
  for (const [name, v] of packages.value) lines.push(`- ${name}: ${v}`)
  return lines.join('\n')
})

async function copyReport(): Promise<void> {
  try {
    await navigator.clipboard.writeText(report.value)
    copied.value = true
    window.setTimeout(() => (copied.value = false), 2000)
  } catch {
    // Clipboard is unavailable over plain http on some browsers; the table is
    // still selectable by hand.
  }
}

onMounted(async () => {
  try {
    info.value = await getJSON<AboutInfo>('/api/about')
  } catch {
    /* client handles 401; the header still renders from /api/auth/me */
  } finally {
    loaded.value = true
  }
})
</script>

<template>
  <div class="page about-page">
    <section class="card about-hero">
      <img class="hero-mark" src="/img/logo.svg" alt="" aria-hidden="true" />
      <div>
        <h2>Synopticon <span class="muted" v-if="version">v{{ version }}</span></h2>
        <p class="muted">
          为群晖照片 (Synology Photos) 提供增强的人脸识别辅助工具：从 NAS 同步图库，运行多模型集成检测与特征提取流程，按人物聚类分组并与群晖现有人物标签交叉比对，经人工审核后将修正结果安全写回群晖。
        </p>
        <div class="cta-row">
          <a class="btn btn-action" :href="repo" target="_blank" rel="noopener noreferrer"
            >访问 GitHub 仓库</a
          >
          <a
            class="btn btn-ghost"
            :href="repo + '/issues/new'"
            target="_blank"
            rel="noopener noreferrer"
            >反馈问题</a
          >
          <a
            class="btn btn-ghost"
            :href="repo + '/blob/main/LICENSE'"
            target="_blank"
            rel="noopener noreferrer"
            >开源许可证</a
          >
        </div>
      </div>
    </section>

    <section class="card about-card">
      <div class="card-head">
        <h3>构建与运行环境</h3>
        <button
          v-if="info"
          class="btn btn-sm"
          type="button"
          @click="copyReport"
          :aria-label="'复制环境信息'"
        >
          {{ copied ? '已复制' : '复制用于问题反馈' }}
        </button>
      </div>
      <table v-if="info" class="data about-table">
        <tbody>
          <tr v-for="r in rows" :key="r.label">
            <th scope="row">{{ r.label }}</th>
            <td :class="{ mono: r.mono }">{{ r.value }}</td>
          </tr>
        </tbody>
      </table>
      <p v-else-if="loaded" class="muted">暂时无法获取环境信息。</p>
      <p v-else class="muted">加载中…</p>
    </section>

    <section class="card about-card" v-if="packages.length">
      <h3>已安装依赖组件</h3>
      <table class="data about-table">
        <tbody>
          <tr v-for="[name, v] in packages" :key="name">
            <th scope="row" class="mono">{{ name }}</th>
            <td class="mono">{{ v }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </div>
</template>

<style scoped>
.about-hero {
  display: flex;
  gap: var(--sp-4);
  align-items: flex-start;
  max-width: 820px;
}
.hero-mark {
  width: 48px;
  height: 48px;
  flex: 0 0 auto;
}
.about-hero h2 {
  margin: 0 0 var(--sp-2);
}
.about-hero p {
  margin: 0;
  max-width: 60ch;
}
.about-card {
  margin-top: var(--sp-4);
  max-width: 820px;
}
.card-head {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.card-head h3 {
  flex: 1;
}
.about-table {
  width: 100%;
  margin-top: var(--sp-3);
}
.about-table th {
  width: 200px;
  white-space: nowrap;
  color: var(--text-2);
  font-weight: 500;
}
.about-table td {
  word-break: break-word;
}
</style>
