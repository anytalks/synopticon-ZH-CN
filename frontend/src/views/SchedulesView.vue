<script setup lang="ts">
// Schedules: saved jobs on a cron timer, fired by the scheduler thread in the
// web process (web/scheduler.py). The form is driven entirely by the catalog the
// server sends with the listing — the param whitelist lives in web/jobs.py, so
// hand-writing the fields here would guarantee drift.
//
// Two things the server owns and this view only surfaces: the typed-phrase tier
// is unschedulable (a 422 with an explanation), and consent booleans are stored
// on the schedule and replayed at fire time, never a stored argv.
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import JobPanel from '../components/JobPanel.vue'
import { getJSON, postJSON, putJSON, deleteJSON, ApiError } from '../api/client'
import { toast } from '../stores/toasts'
import { confirm } from '../composables/useConfirm'
import type {
  Schedule,
  ScheduleJobForm,
  ScheduleFormField,
  SchedulesResponse,
} from '../api/types'

const PRESETS: { label: string; cron: string }[] = [
  { label: '每小时', cron: '@hourly' },
  { label: '每 6 小时', cron: '0 */6 * * *' },
  { label: '每天凌晨 3 点', cron: '0 3 * * *' },
  { label: '每周日凌晨 4 点', cron: '0 4 * * SUN' },
  { label: '每月 1 日凌晨 5 点', cron: '0 5 1 * *' },
]

const JOB_COPY: Record<string, { label: string; description: string; warning?: string }> = {
  sync: {
    label: '同步图库',
    description: '从群晖 NAS 拉取新照片、相册与群晖人物标签，仅读取，不修改群晖。',
  },
  extract: {
    label: '人脸检测与提取',
    description: '扫描尚未处理的照片，检测并记录所有出现的人脸与特征。',
  },
  cluster: {
    label: '人脸聚类分组',
    description: '将检测到的人脸按人物聚类分组，与群晖已有的人物比对，并生成人脸审核建议。',
  },
  recluster: {
    label: '重新聚类分组（离线）',
    description: '使用已保存的配置，基于本地现有数据重新聚类分组，不会访问群晖 NAS。',
  },
  'regen-crops': {
    label: '重新生成人脸头像',
    description: '重新生成人脸审核界面所需的人脸裁切图。',
  },
  report: {
    label: '生成静态 HTML 报告',
    description: '重新生成可独立打开查看的静态审核报告。',
  },
  apply: {
    label: '写回修正到群晖',
    description: '将已通过的审核决定写回群晖 NAS。除非取消勾选“仅预演”，否则默认只执行预演。',
    warning:
      '定时写回会在无人值守时修改群晖照片数据。“合并已命名人物”无法设为定时任务，每次均须手动输入确认短语。',
  },
  dedupe: {
    label: '重复照片去重（预演）',
    description:
      '根据已存哈希列出重复照片。真正删除重复照片无法设为定时任务，每次均须手动输入确认短语。',
  },
  'clear-queue': {
    label: '清空审核队列',
    description: '移除所有待审核的识别建议。已通过和已写回的决定将会保留。',
  },
  'clear-applies': {
    label: '清空待写回队列',
    description:
      '将尚未写回群晖和写回失败的已通过决定退回待审核队列。不会删除任何数据，也不会修改群晖。',
  },
  'delete-crops': {
    label: '删除人脸头像缓存',
    description: '清空本地缓存的人脸裁切图以释放磁盘空间。',
  },
}

const FIELD_LABELS: Record<string, { label: string; help?: string }> = {
  space: { label: '空间', help: '留空则覆盖所有已配置的空间。' },
  hash: { label: '计算内容哈希', help: '对应命令行参数 --hash' },
  skip_faces: { label: '跳过群晖人脸' },
  all_faces: { label: '重新拉取全部人脸' },
  limit: { label: '数量上限' },
  'extract.limit': { label: '照片数量上限', help: '填 0 或留空表示不限制。' },
  only_missing: { label: '仅生成缺失头像', help: '取消勾选则会重建全部头像（--all）。' },
  kinds: { label: '建议类型', help: '留空则采用默认范围：归属认领 + 低置信度复核。' },
  dry_run: { label: '仅预演（不修改群晖）', help: '仅预览将要执行的操作，不写入任何修改。' },
  apply_reassigns: { label: '允许改判人物' },
  apply_merges: { label: '允许合并未命名分组' },
  exact: { label: '完全一致（SHA-256 字节相同）' },
  visual: { label: '视觉相似（pHash 近似重复）' },
  threshold: { label: 'pHash 汉明距离阈值', help: '范围 0–64，默认为 6。' },
}

const OPTION_LABELS: Record<string, string> = {
  '': '全部',
  personal: '个人空间',
  shared: '共享空间',
  assign: '归属认领',
  low_confidence: '低置信度复核',
  new_person: '发现新人物',
  reassign: '改判人物',
  merge: '合并未命名分组',
  merge_named: '合并已命名人物',
}

const RUN_STATUS_LABELS: Record<string, string> = {
  submitted: '已提交',
  skipped: '已跳过',
  missed: '已错过',
  error: '出错',
}

const JOB_STATE_LABELS: Record<string, string> = {
  queued: '排队中',
  running: '运行中',
  succeeded: '成功',
  ok: '成功',
  done: '已完成',
  failed: '失败',
  cancelled: '已取消',
  interrupted: '已中断',
}

function scheduleJobLabel(job: string, fallback: string): string {
  return JOB_COPY[job]?.label ?? fallback
}

function scheduleJobDesc(spec: ScheduleJobForm): string {
  return JOB_COPY[spec.job]?.description ?? spec.description
}

function scheduleJobWarning(spec: ScheduleJobForm): string {
  return JOB_COPY[spec.job]?.warning ?? spec.warning ?? ''
}

function fieldLabel(job: string, key: string, fallback: string): string {
  return FIELD_LABELS[`${job}.${key}`]?.label ?? FIELD_LABELS[key]?.label ?? fallback
}

function fieldHelp(job: string, f: ScheduleFormField): string {
  return FIELD_LABELS[`${job}.${f.key}`]?.help ?? FIELD_LABELS[f.key]?.help ?? f.help ?? ''
}

function optionLabel(opt: string): string {
  return OPTION_LABELS[opt] ?? opt
}

function runStatusLabel(status: string): string {
  return RUN_STATUS_LABELS[status] ?? status
}

function jobStateLabel(state: string): string {
  return JOB_STATE_LABELS[state] ?? state
}

const items = ref<Schedule[]>([])
const catalog = ref<ScheduleJobForm[]>([])
const loading = ref(true)
const panel = ref<InstanceType<typeof JobPanel> | null>(null)
const expanded = ref<number | null>(null)
/** Re-rendered once a minute so "in 3 hours" does not go stale on an open tab. */
const clock = ref(Date.now())
let ticker: number | null = null

const editing = ref<Schedule | null>(null)
const creating = ref(false)
const saving = ref(false)
const form = reactive({
  name: '',
  job: '',
  cron: '0 3 * * *',
  timezone: '',
  enabled: true,
  confirm: false,
  params: {} as Record<string, unknown>,
})
const preview = ref<number[]>([])
const cronError = ref('')
let previewTimer: number | null = null

const open = computed(() => creating.value || editing.value !== null)
const selectedForm = computed(() => catalog.value.find((j) => j.job === form.job) ?? null)
const zones = computed<string[]>(() => {
  const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] }
  try {
    return intl.supportedValuesOf ? intl.supportedValuesOf('timeZone') : []
  } catch {
    return []
  }
})

// -- formatting -------------------------------------------------------------
function fmtTime(t: number | null | undefined): string {
  return t ? new Date(t * 1000).toLocaleString('zh-CN') : '—'
}

/** "3 小时 20 分钟后" / "12 分钟前". Coarse on purpose — this is a schedule, not a timer. */
function fmtRelative(t: number | null | undefined): string {
  if (!t) return ''
  const delta = t * 1000 - clock.value
  const ahead = delta >= 0
  let s = Math.round(Math.abs(delta) / 1000)
  if (s < 60) return ahead ? '不到 1 分钟后' : '刚刚'
  const d = Math.floor(s / 86400)
  s -= d * 86400
  const h = Math.floor(s / 3600)
  const m = Math.floor((s - h * 3600) / 60)
  const parts = [d ? `${d} 天` : '', h ? `${h} 小时` : '', d ? '' : m ? `${m} 分钟` : ''].filter(Boolean)
  const text = parts.join(' ')
  return ahead ? `${text}后` : `${text}前`
}

// -- loading ----------------------------------------------------------------
async function load(): Promise<void> {
  try {
    const data = await getJSON<SchedulesResponse>('/api/schedules')
    items.value = data.items
    catalog.value = data.jobs
  } catch (e) {
    toast((e as Error).message || '无法加载定时任务', 'error')
  } finally {
    loading.value = false
  }
}

// -- editor -----------------------------------------------------------------
function defaultsFor(job: string): Record<string, unknown> {
  const spec = catalog.value.find((j) => j.job === job)
  const out: Record<string, unknown> = {}
  for (const f of spec?.fields ?? []) {
    if (f.type === 'bool') out[f.key] = f.default === true
    else if (f.type === 'multiselect') out[f.key] = []
    else out[f.key] = f.default ?? ''
  }
  return out
}

function startCreate(): void {
  const first = catalog.value[0]?.job ?? ''
  editing.value = null
  creating.value = true
  Object.assign(form, {
    name: '',
    job: first,
    cron: '0 3 * * *',
    timezone: '',
    enabled: true,
    confirm: false,
    params: defaultsFor(first),
  })
  void refreshPreview()
}

function startEdit(s: Schedule): void {
  creating.value = false
  editing.value = s
  Object.assign(form, {
    name: s.name,
    job: s.job,
    cron: s.cron,
    timezone: s.timezone ?? '',
    enabled: s.enabled,
    confirm: s.confirm,
    params: { ...defaultsFor(s.job), ...s.params },
  })
  void refreshPreview()
}

function closeEditor(): void {
  creating.value = false
  editing.value = null
  preview.value = []
  cronError.value = ''
}

// Changing the job resets to that job's defaults: params are per-job and
// carrying a stale key over would just be rejected by the server's whitelist.
watch(
  () => form.job,
  (job, previous) => {
    if (previous !== undefined && job !== previous) form.params = defaultsFor(job)
  },
)

watch([() => form.cron, () => form.timezone], () => {
  if (previewTimer !== null) window.clearTimeout(previewTimer)
  previewTimer = window.setTimeout(() => void refreshPreview(), 300)
})

async function refreshPreview(): Promise<void> {
  if (!form.cron.trim()) {
    preview.value = []
    cronError.value = ''
    return
  }
  try {
    const res = await postJSON<{ next: number[] }>('/api/schedules/preview', {
      cron: form.cron,
      timezone: form.timezone,
    })
    preview.value = res.next
    cronError.value = ''
  } catch (e) {
    preview.value = []
    cronError.value = e instanceof ApiError ? e.message : '无法解析该 Cron 表达式'
  }
}

/** Drop empty optional fields so the server sees "unset", not "" or NaN. */
function payloadParams(): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const f of selectedForm.value?.fields ?? []) {
    const value = form.params[f.key]
    if (f.type === 'bool') {
      if (value) out[f.key] = true
      else if (f.default === true) out[f.key] = false
    } else if (f.type === 'multiselect') {
      if (Array.isArray(value) && value.length) out[f.key] = value
    } else if (value !== '' && value != null) {
      out[f.key] = value
    }
  }
  return out
}

async function save(): Promise<void> {
  saving.value = true
  const body = {
    name: form.name,
    job: form.job,
    cron: form.cron,
    timezone: form.timezone,
    enabled: form.enabled,
    confirm: form.confirm,
    params: payloadParams(),
  }
  try {
    if (editing.value) await putJSON(`/api/schedules/${editing.value.id}`, body)
    else await postJSON('/api/schedules', body)
    toast(editing.value ? '定时任务已更新' : '定时任务已创建')
    closeEditor()
    await load()
  } catch (e) {
    toast((e as Error).message || '无法保存定时任务', 'error')
  } finally {
    saving.value = false
  }
}

// -- row actions ------------------------------------------------------------
async function toggle(s: Schedule): Promise<void> {
  try {
    await postJSON(`/api/schedules/${s.id}/enabled`, { enabled: !s.enabled })
    await load()
  } catch (e) {
    toast((e as Error).message || '无法更新定时任务', 'error')
  }
}

async function remove(s: Schedule): Promise<void> {
  const ok = await confirm({
    title: '删除定时任务',
    message: `确定要删除“${s.name}”吗？已由此启动的任务不受影响。`,
    okLabel: '删除',
  })
  if (!ok) return
  try {
    await deleteJSON(`/api/schedules/${s.id}`)
    if (editing.value?.id === s.id) closeEditor()
    await load()
  } catch (e) {
    toast((e as Error).message || '无法删除定时任务', 'error')
  }
}

async function runNow(s: Schedule): Promise<void> {
  try {
    const res = await postJSON<{ job_id: string }>(`/api/schedules/${s.id}/run`)
    panel.value?.attach(res.job_id)
    toast(`已启动：${scheduleJobLabel(s.job, s.job_label)}`)
    await load()
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      toast(`未能启动：${(e.body?.detail as string) ?? '同类任务正在运行中'}`, 'error')
    } else {
      toast((e as Error).message || '无法启动任务', 'error')
    }
  }
}

function paramSummary(s: Schedule): string {
  const parts = Object.entries(s.params)
    .filter(([, v]) => v !== '' && v != null && v !== false)
    .map(([k, v]) => {
      const kLabel = fieldLabel(s.job, k, k)
      if (v === true) return kLabel
      const val = Array.isArray(v)
        ? v.map((x) => optionLabel(String(x))).join('+')
        : optionLabel(String(v))
      return `${kLabel}=${val}`
    })
  return parts.join(' · ')
}

function toggleRuns(id: number): void {
  expanded.value = expanded.value === id ? null : id
}

function fieldId(f: ScheduleFormField): string {
  return `sched-field-${f.key}`
}

onMounted(() => {
  void load()
  ticker = window.setInterval(() => (clock.value = Date.now()), 60000)
})
onUnmounted(() => {
  if (ticker !== null) window.clearInterval(ticker)
  if (previewTimer !== null) window.clearTimeout(previewTimer)
})
</script>

<template>
  <div class="page sched-page">
    <JobPanel ref="panel" />

    <section class="card sched-intro">
      <div>
        <h3>定时任务</h3>
        <p class="muted">
          按 Cron 计划自动执行处理流程、实用工具及写回群晖任务。未指定时区时默认使用服务器时区。
        </p>
      </div>
      <button type="button" class="btn btn-primary" @click="startCreate" v-if="!open">
        新建定时任务
      </button>
    </section>

    <!-- Editor -->
    <section v-if="open" class="card sched-editor">
      <h3>{{ editing ? '编辑定时任务' : '新建定时任务' }}</h3>

      <div class="sched-grid">
        <label class="fld">
          <span>名称</span>
          <input class="input" v-model="form.name" placeholder="例如：每日定时同步" />
        </label>

        <label class="fld">
          <span>任务类型</span>
          <select class="select" v-model="form.job">
            <option v-for="j in catalog" :key="j.job" :value="j.job">
              {{ scheduleJobLabel(j.job, j.label) }}
            </option>
          </select>
        </label>
      </div>

      <p v-if="selectedForm" class="muted">{{ scheduleJobDesc(selectedForm) }}</p>
      <p v-if="selectedForm && scheduleJobWarning(selectedForm)" class="sched-warning">
        {{ scheduleJobWarning(selectedForm) }}
      </p>

      <!-- Job params, described by the server catalog -->
      <div v-if="selectedForm?.fields.length" class="sched-params">
        <div v-for="f in selectedForm.fields" :key="f.key" class="fld">
          <label v-if="f.type === 'bool'" class="opt-check">
            <input type="checkbox" v-model="form.params[f.key]" />
            {{ fieldLabel(selectedForm.job, f.key, f.label) }}
          </label>
          <template v-else-if="f.type === 'multiselect'">
            <span>{{ fieldLabel(selectedForm.job, f.key, f.label) }}</span>
            <div class="sched-multi">
              <label v-for="opt in f.options" :key="opt" class="opt-check">
                <input type="checkbox" :value="opt" v-model="(form.params[f.key] as string[])" />
                {{ optionLabel(opt) }}
              </label>
            </div>
          </template>
          <template v-else-if="f.type === 'select'">
            <label :for="fieldId(f)">{{ fieldLabel(selectedForm.job, f.key, f.label) }}</label>
            <select class="select" :id="fieldId(f)" v-model="form.params[f.key]">
              <option v-for="opt in f.options" :key="opt" :value="opt">
                {{ optionLabel(opt) }}
              </option>
            </select>
          </template>
          <template v-else>
            <label :for="fieldId(f)">{{ fieldLabel(selectedForm.job, f.key, f.label) }}</label>
            <input
              class="input"
              :id="fieldId(f)"
              :type="f.type === 'int' ? 'number' : 'text'"
              v-model="form.params[f.key]"
            />
          </template>
          <span v-if="fieldHelp(selectedForm.job, f)" class="muted">{{
            fieldHelp(selectedForm.job, f)
          }}</span>
        </div>
      </div>

      <div class="sched-grid">
        <label class="fld">
          <span>Cron 表达式</span>
          <input class="input mono" v-model="form.cron" placeholder="0 3 * * *" spellcheck="false" />
          <span class="muted">分 时 日 月 星期</span>
        </label>

        <label class="fld">
          <span>时区</span>
          <input
            class="input"
            v-model="form.timezone"
            list="sched-zones"
            placeholder="服务器默认时区"
          />
          <datalist id="sched-zones">
            <option v-for="z in zones" :key="z" :value="z" />
          </datalist>
        </label>
      </div>

      <div class="sched-presets">
        <button
          v-for="p in PRESETS"
          :key="p.cron"
          type="button"
          class="btn btn-sm"
          @click="form.cron = p.cron"
        >
          {{ p.label }}
        </button>
      </div>

      <p v-if="cronError" class="sched-error" role="alert">{{ cronError }}</p>
      <p v-else-if="preview.length" class="muted">
        接下来几次运行时间：<span class="mono">{{ preview.map(fmtTime).join(' · ') }}</span>
      </p>

      <div class="sched-consent">
        <label class="opt-check">
          <input type="checkbox" v-model="form.enabled" />
          启用此定时任务
        </label>
        <label v-if="selectedForm?.needs_confirm" class="opt-check">
          <input type="checkbox" v-model="form.confirm" />
          我已知晓该任务会在无人值守时自动运行，且可能会修改群晖 NAS 数据
        </label>
      </div>

      <div class="sched-actions">
        <button type="button" class="btn btn-primary" :disabled="saving" @click="save">
          {{ editing ? '保存修改' : '创建定时任务' }}
        </button>
        <button type="button" class="btn" @click="closeEditor">取消</button>
      </div>
    </section>

    <!-- Listing -->
    <p v-if="loading" class="muted">正在加载…</p>
    <p v-else-if="!items.length" class="muted">
      暂无定时任务。「处理流程」「实用工具」与「写回群晖」中的大部分操作均可在此设为定时执行；需要手动输入确认短语的高风险操作除外，始终保持手动执行。
    </p>

    <section v-for="s in items" :key="s.id" class="card sched-card" :class="{ off: !s.enabled }">
      <div class="sched-head">
        <div class="sched-title">
          <strong>{{ s.name }}</strong>
          <span class="badge">{{ scheduleJobLabel(s.job, s.job_label) }}</span>
          <span v-if="!s.enabled" class="badge state-cancelled">已停用</span>
          <span
            v-else-if="s.last_status && s.last_status !== 'submitted'"
            class="badge"
            :class="s.last_status === 'error' ? 'state-failed' : 'state-queued'"
            >{{ runStatusLabel(s.last_status) }}</span
          >
        </div>
        <div class="sched-buttons">
          <button type="button" class="btn btn-sm" @click="runNow(s)">立即运行</button>
          <button type="button" class="btn btn-sm" @click="startEdit(s)">编辑</button>
          <button type="button" class="btn btn-sm" @click="toggle(s)">
            {{ s.enabled ? '停用' : '启用' }}
          </button>
          <button type="button" class="btn btn-sm btn-danger" @click="remove(s)">删除</button>
        </div>
      </div>

      <div class="sched-meta muted">
        <span class="mono">{{ s.cron }}</span>
        <span v-if="s.timezone">· {{ s.timezone }}</span>
        <span v-if="paramSummary(s)">· {{ paramSummary(s) }}</span>
      </div>

      <div class="sched-meta">
        <span v-if="s.enabled">
          下次运行：<strong>{{ fmtTime(s.next_run_at) }}</strong>
          <span class="muted">（{{ fmtRelative(s.next_run_at) }}）</span>
        </span>
        <span v-else class="muted">未排程</span>
        <span class="muted">
          · 上次运行：{{ fmtTime(s.last_run_at) }}
          <template v-if="s.last_run_at">（{{ fmtRelative(s.last_run_at) }}）</template>
        </span>
        <button
          v-if="s.runs && s.runs.length"
          type="button"
          class="btn btn-ghost btn-sm"
          @click="toggleRuns(s.id)"
        >
          {{ expanded === s.id ? '收起记录' : `运行记录（${s.runs.length}）` }}
        </button>
      </div>

      <ul v-if="expanded === s.id" class="sched-runs">
        <li v-for="r in s.runs" :key="r.id">
          <span class="mono">{{ fmtTime(r.fired_at) }}</span>
          <span class="badge" :class="r.status === 'error' ? 'state-failed' : ''">{{
            runStatusLabel(r.status)
          }}</span>
          <RouterLink v-if="r.job_id" :to="`/jobs/${r.job_id}`" class="mono"
            >#{{ r.job_id }}</RouterLink
          >
          <span v-if="r.job_state" class="badge" :class="`state-${r.job_state}`">{{
            jobStateLabel(r.job_state)
          }}</span>
          <span v-if="r.detail" class="muted">{{ r.detail }}</span>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.sched-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.sched-intro {
  display: flex;
  gap: var(--sp-3);
  align-items: flex-start;
  justify-content: space-between;
}
.sched-intro h3,
.sched-editor h3 {
  margin: 0 0 var(--sp-1);
}
.sched-editor {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.sched-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--sp-3);
}
.sched-params {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--sp-2);
  padding: var(--sp-2);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
}
.fld {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--fs-sm);
}
.sched-multi {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}
.opt-check {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}
.sched-presets {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1);
}
.sched-consent,
.sched-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  align-items: center;
}
.sched-warning {
  color: var(--danger);
  font-size: var(--fs-sm);
  margin: 0;
}
.sched-error {
  color: var(--danger);
  font-size: var(--fs-sm);
  margin: 0;
}
.sched-card {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.sched-card.off {
  opacity: 0.65;
}
.sched-head {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  align-items: center;
  justify-content: space-between;
}
.sched-title {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.sched-buttons {
  display: flex;
  gap: var(--sp-1);
  flex-wrap: wrap;
}
.sched-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1);
  align-items: center;
  font-size: var(--fs-sm);
}
.sched-runs {
  list-style: none;
  margin: 0;
  padding: var(--sp-2);
  border-top: 1px solid var(--border-soft);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  font-size: var(--fs-sm);
}
.sched-runs li {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  flex-wrap: wrap;
}
</style>
