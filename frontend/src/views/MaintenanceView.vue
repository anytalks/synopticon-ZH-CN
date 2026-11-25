<script setup lang="ts">
// Maintenance page: one card per destructive local-state command with live
// "what will be removed" counts. Those come from four /api/maintenance/*
// endpoints fetched in parallel, split by cost, so a slow table count or crops
// walk only holds back its own card. Consent (plan §6) is
// enforced by the shared confirm dialog: clear-queue / clear-applies /
// prune-queue / delete-crops / reset take a plain confirm, reset --all takes the typed phrase
// "reset all". Each action submits a job so the shared JobPanel streams its
// progress. The server's validate_consent re-checks every gate regardless.
// Photo deduplication lives on the Utilities page — it acts on the NAS library,
// not on local pipeline state.
import { ref, reactive, onMounted } from 'vue'
import JobPanel from '../components/JobPanel.vue'
import { getJSON, ApiError } from '../api/client'
import { toast } from '../stores/toasts'
import { confirm } from '../composables/useConfirm'

const PHRASE_RESET_ALL = 'reset all'

interface OrphanCounts {
  by_status?: Record<string, number>
  prunable?: number | null
}

interface QueueCounts {
  pending_queue: number | null
  queued_applies: { approved: number | null; failed: number | null }
}
interface TableCounts {
  faces: number | null
  embeddings: number | null
  cluster_runs: number | null
  photos: number | null
}
interface CropUsage {
  files: number | null
  bytes: number | null
}

// A section is pending until its first response; a reload after a job keeps the
// previous figures on screen rather than flashing spinners back in.
function section<T>(url: string) {
  const data = ref<T | null>(null)
  const loading = ref(true)
  async function load(): Promise<void> {
    loading.value = true
    try {
      data.value = await getJSON<T>(url)
    } catch {
      /* transient */
    } finally {
      loading.value = false
    }
  }
  return { data, pending: () => loading.value && data.value == null, load }
}

const queue = section<QueueCounts>('/api/maintenance/counts')
const tables = section<TableCounts>('/api/maintenance/tables')
const orphans = section<OrphanCounts>('/api/maintenance/orphans')
const crops = section<CropUsage>('/api/maintenance/crops')
const panel = ref<InstanceType<typeof JobPanel> | null>(null)

const reset = reactive({ all: false, keepCrops: false })

const STATUS_LABELS: Record<string, string> = {
  pending: '待审核',
  approved: '已通过',
  rejected: '已拒绝',
  applied: '已写回',
  failed: '写回失败',
  deferred: '已暂缓',
  skipped: '已跳过',
}

function fmtBytes(n: number | null | undefined): string {
  if (n == null) return '未知'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024
    i++
  }
  return (i === 0 ? v : v.toFixed(1)) + ' ' + u[i]
}

function show(v: number | null | undefined): string {
  return v == null ? '—' : String(v)
}

const cropsText = () => {
  const c = crops.data.value
  if (!c || c.files == null) return '未知'
  return `${c.files} 个文件 · ${fmtBytes(c.bytes)}`
}

function loadCounts(): void {
  void Promise.all([queue.load(), tables.load(), orphans.load(), crops.load()])
}

function startJob(
  name: string,
  params: Record<string, unknown> = {},
  extra: Record<string, unknown> = {},
): void {
  panel.value
    ?.start(name, params, extra)
    .then(() => window.setTimeout(loadCounts, 500))
    .catch((e: unknown) => {
      if (e instanceof ApiError && e.status === 428) toast('需要确认授权才能继续。', 'error')
      else toast((e as Error).message || '启动任务失败', 'error')
    })
}

async function clearQueue(): Promise<void> {
  const ok = await confirm({
    title: '清空审核队列',
    message: '确定移除所有待审核的识别建议吗？已通过和已写回的决定将会保留。',
    okLabel: '清空队列',
  })
  if (ok) startJob('clear-queue', {}, { confirm: true })
}

const queuedApplies = () => {
  const q = queue.data.value?.queued_applies
  return (q?.approved || 0) + (q?.failed || 0)
}

async function clearApplies(): Promise<void> {
  const ok = await confirm({
    title: '清空待写回队列',
    message:
      '确定将尚未写回群晖 NAS 的已通过决定（以及写回失败的条目）退回人脸审核队列吗？不会删除任何数据，已成功写回的决定也会保留。',
    okLabel: '清空待写回队列',
  })
  if (ok) startJob('clear-applies', {}, { confirm: true })
}

// Orphans a human already decided on are counted but never pruned by default:
// an approved one still writes to the NAS from its stored payload, so it is worth
// naming in the dialog rather than sweeping up silently.
const pruneOpts = reactive({ includeApproved: false })

const prunable = () => orphans.data.value?.prunable ?? null
const decidedOrphans = () => {
  const by = orphans.data.value?.by_status
  if (!by) return 0
  return Object.entries(by)
    .filter(([s]) => s !== 'pending' && s !== 'rejected')
    .reduce((n, [, v]) => n + v, 0)
}
const orphanBreakdown = () => {
  const by = orphans.data.value?.by_status
  if (!by || Object.keys(by).length === 0) return '无'
  return Object.entries(by)
    .sort((a, b) => b[1] - a[1])
    .map(([s, n]) => `${STATUS_LABELS[s] ?? s} ${n} 条`)
    .join(' · ')
}

async function pruneQueue(): Promise<void> {
  const decided = decidedOrphans()
  const extra =
    pruneOpts.includeApproved && decided > 0
      ? ` 此操作同时会移除你已做出决定的 ${decided} 条记录。`
      : ''
  const ok = await confirm({
    title: '清理失效审核项',
    message:
      '确定删除对应人脸已不存在的审核项吗？相关照片已被重新检测，这些旧项已无法显示或写回——运行「人脸聚类分组」即可基于最新人脸重新生成建议。' +
      extra,
    okLabel: '清理失效项',
  })
  if (ok) startJob('prune-queue', { include_approved: pruneOpts.includeApproved }, { confirm: true })
}

async function deleteCrops(): Promise<void> {
  const ok = await confirm({
    title: '删除人脸头像缓存',
    message: '确定清空所有本地缓存的人脸裁切图吗？后续可随时通过重新生成头像（regen-crops）重建。',
    okLabel: '删除缓存',
  })
  if (ok) startJob('delete-crops', {}, { confirm: true })
}

async function runReset(): Promise<void> {
  const params: Record<string, unknown> = { keep_crops: reset.keepCrops }
  if (reset.all) {
    params.all = true
    const ok = await confirm({
      title: '完全重置所有本地数据',
      message:
        '此操作会清空包括已同步照片在内的全部本地处理数据。群晖 NAS 不会受到任何影响，但你需要重新同步图库。',
      phrase: PHRASE_RESET_ALL,
      okLabel: '确认完全重置',
    })
    if (ok) startJob('reset', params, { confirm_phrase: PHRASE_RESET_ALL })
  } else {
    const ok = await confirm({
      title: '重置本地数据库',
      message: '确定清空本地数据库中的人脸、特征向量、人脸分组与审核队列吗？',
      okLabel: '确认重置',
    })
    if (ok) startJob('reset', params, { confirm: true })
  }
}

onMounted(loadCounts)
</script>

<template>
  <div class="page">
    <JobPanel ref="panel" @done="loadCounts" />

    <div class="maint-grid" style="margin-top: var(--sp-4)">
      <section class="card maint-card">
        <h3>清空审核队列</h3>
        <p class="muted">移除所有待审核的识别建议。已通过和已写回的决定不受影响。</p>
        <p>
          待审核项：
          <span class="maint-count"
            ><span v-if="queue.pending()" class="spinner" aria-label="加载中"></span
            ><template v-else>{{ show(queue.data.value?.pending_queue) }}</template></span
          >
        </p>
        <div class="maint-actions">
          <button type="button" class="btn btn-danger" @click="clearQueue">清空队列…</button>
        </div>
      </section>

      <section class="card maint-card">
        <h3>清空待写回队列</h3>
        <p class="muted">
          将尚未写回群晖以及写回失败的已通过决定退回审核队列。已写回的决定将会保留。
        </p>
        <p v-if="queue.pending()">
          待写回：<span class="spinner" aria-label="加载中"></span>
        </p>
        <p v-else>
          待写回：
          <span class="maint-count">{{ show(queue.data.value?.queued_applies?.approved) }}</span> ·
          写回失败：<span class="maint-count">{{ show(queue.data.value?.queued_applies?.failed) }}</span>
        </p>
        <div class="maint-actions">
          <button
            type="button"
            class="btn btn-danger"
            :disabled="queuedApplies() === 0"
            @click="clearApplies"
          >
            清空待写回队列…
          </button>
        </div>
      </section>

      <section class="card maint-card">
        <h3>清理失效审核项</h3>
        <p class="muted">
          由于照片重新检测导致人脸 ID 变更而失效的条目。它们无法显示头像，也无法通过「重新生成头像」修复；清理后运行「人脸聚类分组」即可基于最新人脸重新生成建议。
        </p>
        <p>
          失效项：
          <span class="maint-count"
            ><span v-if="orphans.pending()" class="spinner" aria-label="加载中"></span
            ><template v-else>{{ orphanBreakdown() }}</template></span
          >
        </p>
        <div class="maint-opts">
          <label class="opt-check"
            ><input type="checkbox" v-model="pruneOpts.includeApproved" /> 同时清理我已做过决定的条目（{{
              decidedOrphans()
            }}）</label
          >
        </div>
        <div class="maint-actions">
          <button
            type="button"
            class="btn btn-danger"
            :disabled="!prunable() && !(pruneOpts.includeApproved && decidedOrphans() > 0)"
            @click="pruneQueue"
          >
            清理失效项…
          </button>
        </div>
      </section>

      <section class="card maint-card">
        <h3>删除人脸头像缓存</h3>
        <p class="muted">
          清空本地缓存的人脸裁切图以释放磁盘空间，后续可按需通过 <code>regen-crops</code> 重新生成。
        </p>
        <p>
          磁盘占用：
          <span class="maint-count"
            ><span v-if="crops.pending()" class="spinner" aria-label="加载中"></span
            ><template v-else>{{ cropsText() }}</template></span
          >
        </p>
        <div class="maint-actions">
          <button type="button" class="btn btn-danger" @click="deleteCrops">删除缓存…</button>
        </div>
      </section>

      <section class="card maint-card danger-card">
        <h3>重置本地数据库</h3>
        <p class="muted">清空本地数据库中的处理流程数据，不会修改群晖 NAS 上的任何内容。</p>
        <p v-if="tables.pending()">
          人脸：<span class="spinner" aria-label="加载中"></span>
        </p>
        <p v-else>
          人脸：<span class="maint-count">{{ show(tables.data.value?.faces) }}</span> ·
          特征向量：<span class="maint-count">{{ show(tables.data.value?.embeddings) }}</span> ·
          聚类次数：<span class="maint-count">{{ show(tables.data.value?.cluster_runs) }}</span> ·
          照片：<span class="maint-count">{{ show(tables.data.value?.photos) }}</span>
        </p>
        <div class="maint-opts">
          <label class="opt-check"
            ><input type="checkbox" v-model="reset.all" /> 完全重置所有本地数据（--all，包含已同步的照片记录）</label
          >
          <label class="opt-check"
            ><input type="checkbox" v-model="reset.keepCrops" /> 保留人脸头像缓存（--keep-crops）</label
          >
        </div>
        <div class="maint-actions">
          <button type="button" class="btn btn-danger" @click="runReset">重置…</button>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.maint-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: var(--sp-3);
}
.maint-card {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.maint-card h3 {
  margin: 0;
}
.maint-card.danger-card {
  border-color: var(--danger);
  box-shadow: 0 0 0 1px var(--danger) inset;
}
.maint-count {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}
.maint-card .spinner {
  display: inline-block;
  vertical-align: middle;
}
.maint-opts {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.maint-opts .opt-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.maint-opts label {
  font-size: var(--fs-sm);
}
.opt-check {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}
.maint-actions {
  display: flex;
  gap: var(--sp-2);
  margin-top: auto;
  padding-top: var(--sp-2);
}
</style>
