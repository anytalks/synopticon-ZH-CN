<script setup lang="ts">
// Dashboard: stat tiles + a sync→detect→group→review→apply strip + an audit
// tail, all from /api/stats + /api/audit (the old window.SYN_* server embeds are
// gone — we fetch on mount instead). Stats are pulled on mount and then only
// while (or just after) a job runs; the "is a job running" signal comes from the
// shared jobs store rather than a second /api/jobs timer of our own. The empty-DB
// CTA replaces the tiles when nothing is synced yet.
import { ref, computed, onMounted, watch } from 'vue'
import { getJSON } from '../api/client'
import { useJobs } from '../stores/jobs'
import { ago } from '../utils/time'
import StatTile from '../components/stats/StatTile.vue'
import type { Stats, AuditEntry } from '../api/types'

const stats = ref<Stats | null>(null)
const audit = ref<AuditEntry[]>([])
const loaded = ref(false)
const { state: jobs } = useJobs()

function num(n: unknown): string {
  return (Number(n) || 0).toLocaleString('zh-CN')
}

function spaceLabel(sp: string): string {
  if (sp === 'personal') return '个人空间'
  if (sp === 'shared') return '共享空间'
  return sp
}

const REVIEW_STATUS_LABELS: Record<string, string> = {
  pending: '待审核',
  approved: '已通过',
  applied: '已写回',
  rejected: '已拒绝',
  hidden: '已隐藏',
  failed: '失败',
}

function reviewStatusLabel(st: string): string {
  return REVIEW_STATUS_LABELS[st] ?? st
}

function sumKinds(byKind: Record<string, number> | undefined): number {
  let t = 0
  for (const k of Object.keys(byKind || {})) t += byKind?.[k] || 0
  return t
}

function statusTotal(status: string): number {
  return sumKinds(stats.value?.review?.[status])
}

const empty = computed(() => {
  const s = stats.value
  if (!s) return false
  const synced = Object.values(s.photos || {}).reduce((a, p) => a + (p.synced || 0), 0)
  return synced === 0 && Number(s.faces || 0) === 0
})

interface Tile {
  label: string
  value: string
  sub?: string
  to?: string | { path: string; query: Record<string, string> }
  hint?: { text: string; linkText: string; to: string } // "Download models" style sub
}

const tiles = computed<Tile[]>(() => {
  const s = stats.value
  if (!s) return []
  const out: Tile[] = []

  for (const [space, p] of Object.entries(s.photos || {})) {
    const sub =
      num(p.hashed) + ' 张已计算哈希' + (p.deleted ? ' · ' + num(p.deleted) + ' 张已删除' : '')
    out.push({ label: '照片 · ' + spaceLabel(space), value: num(p.synced), sub, to: '/pipeline' })
  }

  out.push({
    label: '人脸',
    value: num(s.faces),
    sub: num(s.embeddings) + ' 条特征向量',
    to: '/pipeline',
  })

  const ex = s.extract || {}
  if (!ex.models_ready) {
    out.push({
      label: '已扫描照片',
      value: '—',
      hint: { text: '以启用人脸检测', linkText: '下载模型', to: '/pipeline' },
    })
  } else {
    const pct =
      ex.coverage != null ? '已覆盖 ' + Math.round(ex.coverage * 100) + '%' : '暂无可扫描照片'
    out.push({
      label: '已扫描照片',
      value: num(ex.processed) + ' / ' + num(ex.eligible),
      sub: pct,
      to: '/pipeline',
    })
  }

  const cl = s.cluster
  if (cl) {
    out.push({
      label: '人脸分组',
      value: num(cl.clusters),
      sub: '第 #' + cl.run_id + ' 次聚类 · ' + ago(cl.created_at),
      to: '/pipeline',
    })
  } else {
    out.push({ label: '人脸分组', value: '—', sub: '尚未聚类分组', to: '/pipeline' })
  }

  return out
})

const reviewPending = computed(() => statusTotal('pending'))
const reviewBreakdown = computed(() =>
  (['approved', 'applied', 'rejected', 'hidden', 'failed'] as const)
    .map((st) => ({ st, n: statusTotal(st) }))
    .filter((r) => r.n > 0),
)

interface Stage {
  label: string
  to: string | { path: string; query: Record<string, string> }
  state: 'pending' | 'active' | 'done'
  note: string
}

const stages = computed<Stage[]>(() => {
  const s = stats.value
  if (!s) return []
  const synced = Object.values(s.photos || {}).reduce((a, p) => a + (p.synced || 0), 0)

  const ex = s.extract || {}
  let exState: Stage['state']
  let exNote: string
  if (!ex.models_ready) {
    exState = 'pending'
    exNote = '缺少模型'
  } else if (ex.eligible > 0 && ex.processed != null && ex.processed >= ex.eligible) {
    exState = 'done'
    exNote = '已完成'
  } else if ((ex.processed ?? 0) > 0) {
    exState = 'active'
    exNote = num(ex.processed) + ' / ' + num(ex.eligible)
  } else {
    exState = 'pending'
    exNote = '未开始'
  }

  const cl = s.cluster
  const pending = statusTotal('pending')
  const approved = statusTotal('approved')
  const applied = statusTotal('applied')
  // Hidden items are reviewed items — a human decided "never again" — so they
  // count toward the queue being worked through.
  const totalItems =
    pending +
    approved +
    applied +
    statusTotal('rejected') +
    statusTotal('hidden') +
    statusTotal('failed')

  let revState: Stage['state']
  let revNote: string
  if (totalItems === 0) {
    revState = 'pending'
    revNote = '暂无项目'
  } else if (pending > 0) {
    revState = 'active'
    revNote = num(pending) + ' 项待审核'
  } else {
    revState = 'done'
    revNote = '已全部审核'
  }

  let apState: Stage['state']
  let apNote: string
  if (approved > 0) {
    apState = 'active'
    apNote = num(approved) + ' 项已通过'
  } else if (applied > 0) {
    apState = 'done'
    apNote = num(applied) + ' 项已写回'
  } else {
    apState = 'pending'
    apNote = '暂无待写回项'
  }

  return [
    {
      label: '同步图库',
      to: '/pipeline',
      state: synced > 0 ? 'done' : 'pending',
      note: synced > 0 ? '已同步 ' + num(synced) + ' 张' : '未开始',
    },
    { label: '人脸检测与提取', to: '/pipeline', state: exState, note: exNote },
    {
      label: '人脸聚类分组',
      to: '/pipeline',
      state: cl ? 'done' : 'pending',
      note: cl ? num(cl.clusters) + ' 个分组' : '未开始',
    },
    { label: '人脸审核', to: '/review', state: revState, note: revNote },
    { label: '写回群晖', to: '/apply', state: apState, note: apNote },
  ]
})

function auditWhen(it: AuditEntry): string {
  return it.ts ? new Date(Number(it.ts) * 1000).toLocaleString('zh-CN') : '—'
}
function auditSuccess(it: AuditEntry): 1 | 0 | -1 {
  if (it.success === 1 || it.success === true) return 1
  if (it.success === 0 || it.success === false) return 0
  return -1
}

async function pullStats(): Promise<void> {
  const [s, a] = await Promise.all([
    getJSON<Stats>('/api/stats'),
    getJSON<{ items: AuditEntry[] }>('/api/audit?limit=20'),
  ])
  stats.value = s
  audit.value = a.items || []
}

onMounted(async () => {
  try {
    await pullStats()
  } catch {
    /* client handles 401; leave the page in its loading state */
  } finally {
    loaded.value = true
  }
})

// Stats are expensive relative to the job list, so refresh them only when the
// shared store reports a job — and once more when that job finishes, to pick up
// whatever it wrote.
watch(
  () => jobs.running?.id ?? null,
  (now, before) => {
    if (now !== null || before !== null) void pullStats().catch(() => {})
  },
)
</script>

<template>
  <div class="page dashboard-page">
    <div v-if="empty" class="card placeholder-card">
      <h2>暂无数据</h2>
      <p class="muted">
        Synopticon 尚未从你的群晖 NAS 同步数据。请先运行首次图库同步，拉取照片、人物和人脸信息，再进行人脸检测与聚类分组。
      </p>
      <div class="cta-row">
        <RouterLink class="btn btn-action" to="/pipeline">运行首次同步</RouterLink>
        <RouterLink class="btn btn-ghost" to="/setup">打开初始化向导</RouterLink>
      </div>
    </div>

    <template v-else-if="stats">
      <section class="stat-tiles" aria-label="图库统计">
        <StatTile
          v-for="tile in tiles"
          :key="tile.label"
          :label="tile.label"
          :value="tile.value"
          :sub="tile.hint ? undefined : tile.sub"
          :to="tile.to"
        >
          <div v-if="tile.hint" class="tile-hint">
            <RouterLink :to="tile.hint.to">{{ tile.hint.linkText }}</RouterLink
            >{{ tile.hint.text }}
          </div>
        </StatTile>

        <!-- Review queue tile has a breakdown row of decided-status links. -->
        <StatTile
          label="审核队列"
          :value="num(reviewPending)"
          sub="待审核"
          :to="{ path: '/review', query: { status: 'pending' } }"
        >
          <div class="review-breakdown">
            <template v-if="reviewBreakdown.length">
              <RouterLink
                v-for="r in reviewBreakdown"
                :key="r.st"
                :to="{ path: '/review', query: { status: r.st } }"
                >{{ reviewStatusLabel(r.st) }} {{ num(r.n) }}</RouterLink
              >
            </template>
            <span v-else class="muted">暂无审核记录</span>
          </div>
        </StatTile>
      </section>

      <section class="pipeline-strip card" aria-label="处理流程状态">
        <h3 class="sr-only">处理流程状态</h3>
        <div class="strip">
          <template v-for="(s, i) in stages" :key="s.label">
            <span v-if="i > 0" class="stage-sep" aria-hidden="true">›</span>
            <RouterLink class="stage" :class="s.state" :to="s.to">
              <span class="stage-name"
                ><span class="stage-dot" aria-hidden="true"></span>{{ s.label }}</span
              >
              <span class="stage-note">{{ s.note }}</span>
            </RouterLink>
          </template>
        </div>
      </section>

      <section class="card audit-card">
        <h3>近期操作记录</h3>
        <div>
          <p v-if="!audit.length" class="muted">暂无写回记录。</p>
          <table v-else class="data">
            <thead>
              <tr>
                <th>时间</th>
                <th>操作</th>
                <th>结果</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(it, i) in audit" :key="i">
                <td>{{ auditWhen(it) }}</td>
                <td>{{ it.action || '' }}</td>
                <td v-if="auditSuccess(it) === 1" class="audit-ok">✓</td>
                <td v-else-if="auditSuccess(it) === 0" class="audit-fail">✗</td>
                <td v-else>—</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </template>

    <div v-else-if="loaded" class="card">
      <p class="muted">加载中…</p>
    </div>
  </div>
</template>

<style scoped>
.stat-tiles {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: var(--sp-3);
}
.tile-hint {
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.review-breakdown {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
  font-size: var(--fs-sm);
}

.pipeline-strip {
  margin-top: var(--sp-4);
}
.strip {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
}
.stage {
  flex: 1 1 140px;
  min-width: 130px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--sp-2) var(--sp-3);
  border-radius: var(--radius);
  color: var(--text);
}
.stage:hover {
  background: var(--bg-sunken);
  text-decoration: none;
}
.stage-name {
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.stage-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--text-3);
  flex: 0 0 auto;
}
.stage.done .stage-dot {
  background: var(--ok);
}
.stage.active .stage-dot {
  background: var(--action);
}
.stage-note {
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.stage-sep {
  align-self: center;
  color: var(--text-3);
  padding: 0 var(--sp-1);
  font-size: var(--fs-lg);
}

.audit-card {
  margin-top: var(--sp-4);
}
.audit-ok {
  color: var(--ok);
  font-weight: 600;
}
.audit-fail {
  color: var(--danger);
  font-weight: 600;
}
.placeholder-card {
  max-width: 640px;
}
</style>
