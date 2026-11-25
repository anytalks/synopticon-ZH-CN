<script setup lang="ts">
// Pipeline page: command cards → whitelisted option forms → POST /api/jobs via
// the shared JobPanel, plus a job-history table. Ports pipeline.html.j2 +
// pipeline.js. The server is the single validator (JOB_SPECS); the forms only
// collect the params each builder accepts. All Run buttons disable while any job
// is queued/running (read from the shared jobs store, which owns the single
// /api/jobs poller, and refreshed on job-done).
import { computed, ref, reactive } from 'vue'
import JobPanel from '../components/JobPanel.vue'
import { toast } from '../stores/toasts'
import { useJobs } from '../stores/jobs'
import { jobLabel } from '../utils/jobs'
import { jobStateLabel } from '../composables/useJobStream'
import { ago } from '../utils/time'
import type { Job } from '../api/types'

const SPACES: [string, string][] = [
  ['', '全部空间（默认）'],
  ['personal', '个人空间'],
  ['shared', '共享空间'],
]

type Field =
  | { kind: 'space'; param: string }
  | { kind: 'check'; param: string; label: string; default?: boolean }
  | { kind: 'number'; param: string; label: string; placeholder?: string; min?: number; max?: number }
  | { kind: 'text'; param: string; label: string; placeholder?: string }

interface CardDef {
  cmd: string
  title: string
  primary: boolean;
  desc: string
  disclosure?: string
  fields: Field[]
  overrides?: boolean
}

const CARDS: CardDef[] = [
  {
    cmd: 'sync',
    title: '同步图库',
    primary: true,
    desc: '从群晖 NAS 拉取照片目录、人物列表及现有人脸数据。',
    disclosure: '选项',
    fields: [
      { kind: 'space', param: 'space' },
      { kind: 'check', param: 'hash', label: '计算文件内容哈希 (--hash)' },
      { kind: 'check', param: 'skip_faces', label: '跳过人脸同步 (--skip-faces)' },
      { kind: 'check', param: 'all_faces', label: '同步全部人脸 (--all-faces)' },
      { kind: 'check', param: 'resume', label: '从上次同步位置续传', default: true },
    ],
  },
  {
    cmd: 'extract',
    title: '人脸检测与提取',
    primary: true,
    desc: '扫描已同步的照片，检测并提取其中的所有人脸特征。',
    disclosure: '选项',
    fields: [
      { kind: 'space', param: 'space' },
      { kind: 'number', param: 'limit', label: '数量上限', placeholder: '全部', min: 1 },
      { kind: 'number', param: 'photo_id', label: '照片 ID', placeholder: '—', min: 1 },
      {
        kind: 'check',
        param: 'retry_skipped',
        label: '重试此前无法读取的照片 (--retry-skipped)',
      },
    ],
  },
  {
    cmd: 'cluster',
    title: '人脸聚类分组',
    primary: true,
    desc: '按人物将检测到的人脸聚类分组，并与群晖照片中的人物进行比对。',
    fields: [],
  },
  {
    cmd: 'recluster',
    title: '重新聚类分组',
    primary: false,
    desc: '使用新参数重新进行人脸聚类分组。纯离线运行，无需访问群晖 NAS。',
    disclosure: '参数覆盖',
    fields: [],
    overrides: true,
  },
  {
    cmd: 'report',
    title: '生成审核报告',
    primary: false,
    desc: '重新生成静态 HTML 审核报告。',
    disclosure: '选项',
    fields: [{ kind: 'number', param: 'run_id', label: '聚类批次 ID', placeholder: '最新', min: 1 }],
  },
  {
    cmd: 'regen-crops',
    title: '重新生成人脸头像',
    primary: false,
    desc: '根据已保存的人脸框坐标重新裁切生成人脸头像。',
    disclosure: '选项',
    fields: [
      { kind: 'space', param: 'space' },
      { kind: 'check', param: 'only_missing', label: '仅补全缺失的头像', default: true },
      { kind: 'number', param: 'limit', label: '数量上限', placeholder: '全部', min: 1 },
    ],
  },
  {
    cmd: 'benchmark',
    title: '性能基准测试',
    primary: false,
    desc: '抽取部分照片样本，测试当前硬件的人脸检测与提取速度。',
    disclosure: '选项',
    fields: [
      { kind: 'space', param: 'space' },
      { kind: 'number', param: 'limit', label: '样本数量', placeholder: '默认', min: 1 },
      { kind: 'number', param: 'warmup', label: '预热张数', placeholder: '默认', min: 0 },
    ],
  },
  {
    cmd: 'models-download',
    title: '下载模型',
    primary: false,
    desc: '按清单拉取并校验人脸识别模型权重文件。',
    disclosure: '选项',
    fields: [
      {
        kind: 'text',
        param: 'only',
        label: '指定模型',
        placeholder: '逗号分隔的模型键名（留空表示全部）',
      },
      {
        kind: 'check',
        param: 'allow_record_hash',
        label: '记录手动放入的模型哈希值 (--allow-record-hash)',
      },
    ],
  },
]

const GROUPS = [
  { key: 'primary', cards: CARDS.filter((c) => c.primary) },
  { key: 'ops', cards: CARDS.filter((c) => !c.primary) },
]

// Per-card reactive form state, seeded from the field defaults.
const params = reactive<Record<string, Record<string, string | boolean>>>({})
for (const card of CARDS) {
  const p: Record<string, string | boolean> = {}
  for (const f of card.fields) {
    if (f.kind === 'check') p[f.param] = f.default ?? false
    else p[f.param] = ''
  }
  params[card.cmd] = p
}

interface KvRow {
  key: string
  val: string
}
const overrides = reactive<Record<string, KvRow[]>>({})
for (const card of CARDS) if (card.overrides) overrides[card.cmd] = [{ key: '', val: '' }]

const open = reactive<Record<string, boolean>>({})
function toggle(cmd: string): void {
  open[cmd] = !open[cmd]
}

function addKv(cmd: string): void {
  overrides[cmd].push({ key: '', val: '' })
}
function removeKv(cmd: string, i: number): void {
  overrides[cmd].splice(i, 1)
}

function buildOverrides(cmd: string): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const row of overrides[cmd] || []) {
    const k = row.key.trim()
    if (!k) continue
    const raw = row.val.trim()
    let val: unknown
    try {
      val = JSON.parse(raw)
    } catch {
      val = raw
    }
    out[k] = val
  }
  return out
}

function buildParams(card: CardDef): Record<string, unknown> {
  const p = params[card.cmd]
  const out: Record<string, unknown> = {}
  for (const f of card.fields) {
    if (f.kind === 'check') {
      out[f.param] = !!p[f.param]
    } else {
      const s = String(p[f.param] ?? '').trim()
      if (s !== '') out[f.param] = s
    }
  }
  if (card.overrides) out.overrides = buildOverrides(card.cmd)
  return out
}

const panel = ref<InstanceType<typeof JobPanel> | null>(null)
const { state: jobs, refreshJobs } = useJobs()
const history = computed<Job[]>(() => jobs.history)
const running = computed(() => jobs.running !== null)

function lastRunText(m: Job): string {
  if (m.state === 'queued') return '排队中'
  if (m.state === 'running') return '正在运行'
  const text = '上次运行：' + ago(m.started_at ?? m.created_at)
  return m.state === 'succeeded' ? text : `${text} · ${jobStateLabel(m.state)}`
}

function run(card: CardDef): void {
  panel.value
    ?.start(card.cmd, buildParams(card))
    .then(() => void refreshJobs())
    .catch((err: Error) => toast(err.message || '启动任务失败', 'error'))
}

function fmtTime(t: number | null | undefined): string {
  return t ? new Date(t * 1000).toLocaleString('zh-CN') : '—'
}

function fmtDuration(m: Job): string {
  if (!m.started_at) return '—'
  const end = m.ended_at || Date.now() / 1000
  const s = Math.max(0, Math.round(end - m.started_at))
  if (s < 60) return `${s}秒`
  const mm = Math.floor(s / 60)
  const ss = s % 60
  return `${mm}分 ${ss}秒`
}

</script>

<template>
  <div class="page">
    <JobPanel ref="panel" @done="refreshJobs" />

    <template v-for="group in GROUPS" :key="group.key">
      <div v-if="group.key === 'ops'" class="ops-divider">
        <span class="ops-divider-label">其他操作</span>
      </div>

      <div class="cmd-grid" :class="`cmd-grid-${group.key}`">
        <section
          v-for="card in group.cards"
          :key="card.cmd"
          class="card cmd-card"
          :class="{ open: open[card.cmd] }"
        >
          <div class="cmd-head">
            <div>
              <div class="cmd-title">{{ card.title }}</div>
              <div class="cmd-desc">{{ card.desc }}</div>
            </div>
            <template v-if="card.disclosure">
              <div class="cmd-head-spacer"></div>
              <button type="button" class="disclosure" @click="toggle(card.cmd)">
                {{ card.disclosure }}
              </button>
            </template>
          </div>

          <div v-if="card.disclosure" class="cmd-opts">
            <template v-if="card.overrides">
              <p class="muted">
                仅接受 <code>clustering.*</code> / <code>crossref.*</code> 配置项（服务端也会校验）。值为 JSON 格式，例如：<code>0.55</code>、<code>true</code>、<code>"cw"</code>。
              </p>
              <div class="kv-editor">
                <div v-for="(row, i) in overrides[card.cmd]" :key="i" class="kv-row">
                  <input class="input" v-model="row.key" placeholder="clustering.threshold" />
                  <input class="input" v-model="row.val" placeholder="0.55" />
                  <button
                    type="button"
                    class="btn btn-sm btn-ghost"
                    aria-label="移除"
                    @click="removeKv(card.cmd, i)"
                  >
                    &times;
                  </button>
                </div>
              </div>
              <button type="button" class="btn btn-sm" @click="addKv(card.cmd)">
                + 添加覆盖项
              </button>
            </template>

            <template v-for="f in card.fields" :key="f.param">
              <div v-if="f.kind === 'space'" class="opt-row">
                <label>空间</label>
                <select class="select" v-model="params[card.cmd][f.param]">
                  <option v-for="[v, l] in SPACES" :key="v" :value="v">{{ l }}</option>
                </select>
              </div>
              <label v-else-if="f.kind === 'check'" class="opt-check">
                <input type="checkbox" v-model="params[card.cmd][f.param]" /> {{ f.label }}
              </label>
              <div v-else-if="f.kind === 'number'" class="opt-row">
                <label>{{ f.label }}</label>
                <input
                  class="input input-sm"
                  type="number"
                  :min="f.min"
                  :max="f.max"
                  :placeholder="f.placeholder"
                  v-model="params[card.cmd][f.param]"
                />
              </div>
              <div v-else class="opt-row">
                <label>{{ f.label }}</label>
                <input
                  class="input"
                  type="text"
                  :placeholder="f.placeholder"
                  v-model="params[card.cmd][f.param]"
                />
              </div>
            </template>
          </div>

          <div class="cmd-actions">
            <button
              type="button"
              class="btn"
              :class="group.key === 'primary' ? 'btn-action' : 'btn-quiet'"
              :disabled="running"
              @click="run(card)"
            >
              运行
            </button>
            <RouterLink
              v-if="jobs.lastRuns[card.cmd]"
              class="last-run"
              :class="`last-run-${jobs.lastRuns[card.cmd].state}`"
              :to="`/jobs/${jobs.lastRuns[card.cmd].id}`"
              :title="fmtTime(jobs.lastRuns[card.cmd].started_at ?? jobs.lastRuns[card.cmd].created_at)"
            >
              {{ lastRunText(jobs.lastRuns[card.cmd]) }}
            </RouterLink>
          </div>
        </section>
      </div>
    </template>

    <div class="card" style="margin-top: var(--sp-4)">
      <h3>历史任务</h3>
      <p v-if="running" class="run-note">
        当前有任务正在运行，完成后才可启动其他任务。
      </p>
      <table class="data history-table">
        <thead>
          <tr>
            <th>任务</th>
            <th>状态</th>
            <th>开始时间</th>
            <th>结束时间</th>
            <th>耗时</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="!history.length">
            <td colspan="6" class="muted">暂无历史任务。</td>
          </tr>
          <tr v-for="m in history" :key="m.id">
            <td class="hist-name">{{ jobLabel(m.name) }}</td>
            <td><span class="badge" :class="`state-${m.state}`">{{ jobStateLabel(m.state) }}</span></td>
            <td class="hist-time">{{ fmtTime(m.started_at) }}</td>
            <td class="hist-time">{{ fmtTime(m.ended_at) }}</td>
            <td>{{ fmtDuration(m) }}</td>
            <td><RouterLink :to="`/jobs/${m.id}`">查看</RouterLink></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.cmd-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--sp-3);
}
.cmd-grid-primary {
  margin-top: var(--sp-4);
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
}
.cmd-grid-primary .cmd-card {
  min-height: 180px;
  padding: var(--sp-5);
  gap: var(--sp-3);
}
.cmd-grid-primary .cmd-title {
  font-size: var(--fs-xl);
}
.cmd-grid-ops .cmd-card {
  padding: var(--sp-3) var(--sp-4);
}
.cmd-card {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.ops-divider {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin: var(--sp-5) 0 var(--sp-3);
}
.ops-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border-soft);
}
.ops-divider-label {
  font-size: var(--fs-sm);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-2);
}
.btn-quiet {
  background: transparent;
  border-color: var(--border);
  color: var(--text-2);
}
.btn-quiet:hover:not(:disabled) {
  background: var(--bg-sunken);
  color: var(--text);
}
.cmd-head {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
}
.cmd-head .cmd-title {
  font-weight: 600;
  font-size: var(--fs-lg);
}
.cmd-head .cmd-desc {
  color: var(--text-2);
  font-size: var(--fs-sm);
  margin-top: 2px;
}
.cmd-head-spacer {
  flex: 1;
}
.cmd-opts {
  border-top: 1px solid var(--border-soft);
  padding-top: var(--sp-2);
  display: none;
  flex-direction: column;
  gap: var(--sp-2);
}
.cmd-card.open .cmd-opts {
  display: flex;
}
.opt-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.opt-row label {
  font-size: var(--fs-sm);
  color: var(--text-2);
  min-width: 72px;
}
.opt-check {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: var(--fs-sm);
  color: var(--text);
  min-width: 0;
}
.kv-editor {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.kv-row {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
}
.kv-row .input {
  flex: 1;
}
.cmd-actions {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
  margin-top: auto;
}
.last-run {
  margin-left: auto;
  font-size: var(--fs-sm);
  color: var(--text-3);
  text-decoration: none;
}
.last-run:hover {
  color: var(--text);
  text-decoration: underline;
}
.last-run-failed,
.last-run-interrupted {
  /* Could be --danger as well, but the pipeline view is already pretty overwhelming */
  color: var(--text-3);
}
.last-run-running,
.last-run-queued {
  color: var(--action);
}
.disclosure {
  background: transparent;
  border: none;
  color: var(--action);
  cursor: pointer;
  font: inherit;
  font-size: var(--fs-sm);
  padding: 0;
}
.history-table td,
.history-table th {
  white-space: nowrap;
}
.history-table td.hist-name {
  font-weight: 600;
}
.history-table td.hist-time {
  color: var(--text-2);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
}
.run-note {
  font-size: var(--fs-sm);
  color: var(--text-2);
}
</style>
