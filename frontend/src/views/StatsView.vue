<script setup lang="ts">
// Stats: what Synopticon has done over its lifetime (the run ledger + audit log)
// and what the library looks like now. The two halves load independently — the
// library scan is the slow one — and both refetch when a job finishes, taking
// that signal from the shared jobs store rather than a timer of our own.
import { computed, onMounted, shallowReactive, watch } from 'vue'
import { getJSON } from '../api/client'
import { toast } from '../stores/toasts'
import { useJobs } from '../stores/jobs'
import { commandLabel } from '../utils/jobs'
import { ago } from '../utils/time'
import {
  num,
  pct,
  fmtBytes,
  fmtDuration,
  fmtDate,
  fmtMonthOf,
  fmtTakenDate,
  fmtDay,
  fmtMonth,
} from '../utils/format'
import StatTile from '../components/stats/StatTile.vue'
import BarList, { type BarItem, type BarSegment, type BarTone } from '../components/stats/BarList.vue'
import ColumnChart, { type Column } from '../components/stats/ColumnChart.vue'
import type { LifetimeStats, LibraryStats } from '../api/types'

interface Section<T> {
  data: T | null
  loading: boolean
  error: string
}

function useSection<T>(url: string, what: string) {
  const s = shallowReactive<Section<T>>({ data: null, loading: false, error: '' })
  async function load(): Promise<void> {
    if (s.loading) return
    s.loading = true
    try {
      s.data = await getJSON<T>(url)
      s.error = ''
    } catch (e) {
      const msg = (e as Error).message || `无法加载${what}`
      s.error = msg
      toast(msg, 'error')
    } finally {
      s.loading = false
    }
  }
  return { s, load }
}

const { s: life, load: loadLife } = useSection<LifetimeStats>('/api/stats/lifetime', '历史统计数据')
const { s: lib, load: loadLib } = useSection<LibraryStats>('/api/stats/library', '图库统计数据')
const { state: jobs } = useJobs()

function refresh(): void {
  void loadLife()
  void loadLib()
}

onMounted(refresh)

// A job that just left queued/running has written whatever it is going to.
watch(
  () => jobs.running?.id ?? null,
  (now, before) => {
    if (before !== null && now !== before) refresh()
  },
)

// -- shared bits ------------------------------------------------------------

type Part = { text: string; strong?: boolean; to?: string | null; href?: string | null }
interface Fact {
  key: string
  parts: Part[]
}

function monthYear(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString('zh-CN', { month: 'long', year: 'numeric' })
}

function argmax(xs: number[]): number {
  let best = 0
  xs.forEach((v, i) => {
    if (v > xs[best]) best = i
  })
  return best
}

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0)

// -- lifetime ---------------------------------------------------------------

const lifeEmpty = computed(() => {
  const l = life.data
  if (!l) return false
  return l.runs.total === 0 && l.nas.writes_ok + l.nas.writes_failed === 0 && l.review.decided === 0
})

const lifeFacts = computed<Fact[]>(() => {
  const l = life.data
  if (!l) return []
  const out: Fact[] = []
  if (l.work.faces_found > 0) {
    out.push({
      key: 'faces',
      parts: [
        { text: l.tracking_since ? `自 ${monthYear(l.tracking_since)} 起，Synopticon 累计检测到 ` : 'Synopticon 累计检测到 ' },
        { text: num(l.work.faces_found), strong: true },
        { text: ' 张人脸。' },
      ],
    })
  }
  if (l.nas.writes_ok > 0) {
    out.push({
      key: 'writes',
      parts: [
        { text: l.first_nas_write ? `自 ${fmtDate(l.first_nas_write)} 起，已向群晖 NAS 写入 ` : '已向群晖 NAS 写入 ' },
        { text: `${num(l.nas.writes_ok)} 次修改`, strong: true },
        { text: '。' },
      ],
    })
  }
  if (l.runs.total_seconds > 0) {
    out.push({
      key: 'time',
      parts: [
        { text: '累计运行时长：' },
        { text: fmtDuration(l.runs.total_seconds), strong: true },
        { text: `，跨越 ${num(l.runs.active_days)} 个活跃日。` },
      ],
    })
  }
  if (l.runs.longest) {
    out.push({
      key: 'longest',
      parts: [
        { text: '耗时最长的任务：' },
        { text: commandLabel(l.runs.longest.command), strong: true },
        {
          text: `，耗时 ${fmtDuration(l.runs.longest.seconds)}（${fmtDate(l.runs.longest.started_at)}）。`,
        },
      ],
    })
  }
  if (l.runs.busiest_day) {
    out.push({
      key: 'busiest',
      parts: [
        { text: '最忙碌的一天：' },
        { text: fmtDay(l.runs.busiest_day.date), strong: true },
        { text: `，共运行 ${num(l.runs.busiest_day.runs)} 次任务。` },
      ],
    })
  }
  if (l.runs.streak_days >= 2) {
    out.push({
      key: 'streak',
      parts: [
        { text: '当前已连续活跃 ' },
        { text: `${num(l.runs.streak_days)} 天`, strong: true },
        { text: '。' },
      ],
    })
  }
  if (l.review.approval_rate != null) {
    out.push({
      key: 'approval',
      parts: [
        { text: '在你审核过的识别建议中，通过率为 ' },
        { text: pct(l.review.approval_rate), strong: true },
        { text: '。' },
      ],
    })
  }
  return out
})

const lifeTiles = computed(() => {
  const l = life.data
  if (!l) return []
  const r = l.runs
  const runSub = [
    `${num(r.ok)} 次成功`,
    `${num(r.failed)} 次失败`,
    r.cancelled ? `${num(r.cancelled)} 次取消` : '',
  ]
    .filter(Boolean)
    .join(' · ')
  return [
    {
      label: '统计起始',
      value: fmtMonthOf(l.tracking_since),
      sub: `${fmtDate(l.tracking_since)} · ${num(r.active_days)} 个活跃日`,
    },
    { label: '运行次数', value: num(r.total), sub: runSub },
    { label: '累计耗时', value: fmtDuration(r.total_seconds), sub: '已完成任务合计' },
    {
      label: '检出人脸',
      value: num(l.work.faces_found),
      sub: `共扫描 ${num(l.work.photos_scanned)} 张次照片`,
    },
    {
      label: '群晖写入',
      value: num(l.nas.writes_ok),
      sub: `${num(l.nas.writes_failed)} 次失败 · ${num(l.nas.dry_runs)} 次预演`,
    },
    {
      label: '审核决定',
      value: num(l.review.decided),
      sub:
        l.review.approval_rate != null
          ? `通过率 ${pct(l.review.approval_rate)}`
          : '暂无记录',
    },
  ]
})

const RUN_LEGEND: Array<{ tone: BarTone; label: string }> = [
  { tone: 'data', label: '成功' },
  { tone: 'bad', label: '失败' },
  { tone: 'rest', label: '已取消或未完成' },
]

const runItems = computed<BarItem[]>(() =>
  (life.data?.runs.by_command ?? []).map((c): BarItem => {
    const notes = [c.last_run ? '最近 ' + ago(c.last_run) : '', c.seconds ? '累计 ' + fmtDuration(c.seconds) : '']
    return {
      key: c.command,
      label: commandLabel(c.command),
      value: c.total,
      note: notes.filter(Boolean).join(' · '),
      segments: [
        { value: c.ok, tone: 'data', label: '成功' },
        { value: c.failed, tone: 'bad', label: '失败' },
        { value: c.cancelled + c.unfinished, tone: 'rest', label: '已取消或未完成' },
      ],
    }
  }),
)

const runLegend = computed(() => {
  const r = life.data?.runs
  if (!r) return []
  return RUN_LEGEND.filter(
    (l) =>
      (l.tone === 'data' && r.ok) ||
      (l.tone === 'bad' && r.failed) ||
      (l.tone === 'rest' && r.cancelled + r.unfinished),
  )
})

const originItems = computed<BarItem[]>(() => {
  const o = life.data?.runs.by_origin
  if (!o) return []
  return [
    { key: 'cli', label: '命令行 (CLI)', value: o.cli },
    { key: 'gui', label: 'Web 界面', value: o.gui },
    { key: 'schedule', label: '定时任务', value: o.schedule },
    { key: 'mcp', label: 'AI 代理 (MCP)', value: o.mcp ?? 0 },
  ]
})

const ACTION_LABELS: Record<string, string> = {
  'assign.add_face': '标记人脸',
  'assign.upload_face': '标记人脸（新建人脸框）',
  'assign.verify': '校验标记生效',
  'reassign.separate': '改判人脸归属',
  'reassign.verify': '校验改判生效',
  merge: '合并人物',
  rename: '命名人物',
  set_show: '显示或隐藏人物',
  delete_face: '删除误检人脸',
  'dedupe.delete': '删除重复照片',
}

/** Audit actions are `<surface>.<what>`; the surface is shown only when it is not the pipeline. */
function actionLabel(action: string): string {
  if (ACTION_LABELS[action]) return ACTION_LABELS[action]
  const dot = action.indexOf('.')
  const surface = dot > 0 ? action.slice(0, dot) : ''
  const rest = dot > 0 ? action.slice(dot + 1) : action
  const base =
    ACTION_LABELS[rest] ??
    rest.replace(/[._]/g, ' ').replace(/^./, (ch) => ch.toUpperCase())
  if (surface === 'quickmerger') return base + '（未命名人物速并）'
  return base
}

const nasItems = computed<BarItem[]>(() =>
  (life.data?.nas.by_action ?? []).map((a): BarItem => ({
    key: a.action,
    label: actionLabel(a.action),
    value: a.ok + a.failed,
    valueText: a.failed ? `${num(a.ok)} · ${num(a.failed)} 次失败` : num(a.ok),
    segments: [
      { value: a.ok, tone: 'data', label: '成功' },
      { value: a.failed, tone: 'bad', label: '失败' },
    ],
  })),
)

const nasHighlights = computed(() => {
  const n = life.data?.nas
  if (!n) return []
  return [
    { label: '已标记人脸', value: n.faces_tagged },
    { label: '已改判人脸', value: n.faces_moved },
    { label: '已合并人物', value: n.merges },
    { label: '已命名人物', value: n.people_named },
    { label: '已删重复照片', value: n.duplicates_deleted },
  ]
})

const workRows = computed(() => {
  const w = life.data?.work
  if (!w) return []
  return [
    { label: '同步照片数', value: w.photos_synced },
    { label: '已扫描照片数', value: w.photos_scanned },
    { label: '检测到的人脸', value: w.faces_found },
    { label: '画质修复增强的人脸', value: w.faces_restored },
    { label: '已计算指纹的照片', value: w.photos_hashed },
    { label: '重新生成的人脸头像', value: w.crops_regenerated },
    { label: '发现的重复照片组', value: w.duplicate_groups_found },
    { label: '清理的失效审核项', value: w.queue_items_pruned },
  ]
})

const reviewItems = computed<BarItem[]>(() => {
  const r = life.data?.review
  if (!r) return []
  return [
    { key: 'approved', label: '通过', value: r.approved },
    { key: 'rejected', label: '拒绝', value: r.rejected },
    { key: 'hidden', label: '永久隐藏', value: r.hidden },
  ]
})

// -- library ----------------------------------------------------------------

// Monday-first order matching the API's by_weekday array.
const weekdayLong = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
const weekdayShort = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

function hourLabel(h: number): string {
  return `${String(h).padStart(2, '0')}:00`
}

const libEmpty = computed(() => (lib.data ? lib.data.photos.total === 0 : false))

const libFacts = computed<Fact[]>(() => {
  const d = lib.data
  if (!d) return []
  const out: Fact[] = []
  const mc = d.people.main_character
  if (mc) {
    out.push({
      key: 'main',
      parts: [
        { text: '图库主角是 ' },
        { text: mc.name, strong: true, href: mc.person_url },
        { text: ` —— 占全部已标记人脸的 ${pct(mc.share)}。` },
      ],
    })
  }
  if (sum(d.photos.by_hour) > 0) {
    out.push({
      key: 'hour',
      parts: [
        { text: '黄金拍摄时段：大多数照片拍摄于 ' },
        { text: hourLabel(argmax(d.photos.by_hour)), strong: true },
        { text: ' 左右。' },
      ],
    })
  }
  if (sum(d.photos.by_weekday) > 0) {
    out.push({
      key: 'weekday',
      parts: [
        { text: '最爱拍照的日子：' },
        { text: weekdayLong[argmax(d.photos.by_weekday)], strong: true },
        { text: '。' },
      ],
    })
  }
  if (d.photos.busiest_day) {
    out.push({
      key: 'busiest',
      parts: [
        { text: '单日拍摄之最：' },
        { text: fmtDay(d.photos.busiest_day.date), strong: true },
        { text: `，共拍摄 ${num(d.photos.busiest_day.count)} 张照片。` },
      ],
    })
  }
  if (d.photos.oldest) {
    out.push({
      key: 'oldest',
      parts: [
        { text: '最早的一张照片拍摄于 ' },
        { text: fmtTakenDate(d.photos.oldest.time), strong: true, to: d.photos.oldest.inspect },
        { text: '。' },
      ],
    })
  }
  if (d.faces.most_crowded && d.faces.most_crowded.faces > 1) {
    out.push({
      key: 'crowded',
      parts: [
        { text: '人最多的一张合影同框收录了 ' },
        { text: `${num(d.faces.most_crowded.faces)} 张人脸`, strong: true, to: d.faces.most_crowded.inspect },
        { text: '。' },
      ],
    })
  }
  return out
})

const span = computed(() => {
  const p = lib.data?.photos
  if (!p?.oldest || !p.newest) return null
  const y = (t: number) => new Date(t * 1000).getUTCFullYear()
  const a = y(p.oldest.time)
  const b = y(p.newest.time)
  return {
    value: num(b - a + 1),
    sub: `${fmtTakenDate(p.oldest.time)} 至 ${fmtTakenDate(p.newest.time)}`,
  }
})

const libTiles = computed(() => {
  const d = lib.data
  if (!d) return []
  const p = d.photos
  const f = d.faces
  const tiles: Array<{ label: string; value: string; sub?: string; to?: string }> = [
    {
      label: '照片总数',
      value: num(p.total),
      sub: fmtBytes(p.bytes) + (p.deleted ? ` · ${num(p.deleted)} 张已删除` : ''),
    },
  ]
  if (span.value) tiles.push({ label: '跨度年数', value: span.value.value, sub: span.value.sub })
  tiles.push(
    {
      label: '检出人脸',
      value: num(f.detected),
      sub: `群晖照片已标记 ${num(f.synology_tagged)} 张`,
    },
    {
      label: '已命名人物',
      value: num(d.people.listed_named),
      sub: d.people.hidden ? `群晖中已隐藏 ${num(d.people.hidden)} 位` : undefined,
    },
    {
      label: '无人物照片',
      value: num(f.photos_without_faces),
      sub: f.photos_scanned
        ? `占已扫描照片的 ${pct(f.photos_without_faces / f.photos_scanned)}`
        : '尚未扫描',
    },
    {
      label: '重复副本',
      value: num(p.duplicate_copies),
      sub: '字节完全相同的多余文件',
      to: p.duplicate_copies ? '/utilities' : undefined,
    },
  )
  return tiles
})

const yearColumns = computed<Column[]>(() =>
  (lib.data?.photos.per_year ?? []).map((y) => ({ label: String(y.year), value: y.count })),
)

const hourColumns = computed<Column[]>(() =>
  (lib.data?.photos.by_hour ?? []).map((v, h) => ({
    label: `${hourLabel(h)}–${String(h).padStart(2, '0')}:59`,
    axis: String(h),
    value: v,
  })),
)

const weekdayColumns = computed<Column[]>(() =>
  (lib.data?.photos.by_weekday ?? []).map((v, i) => ({
    label: weekdayLong[i] ?? String(i),
    axis: weekdayShort[i] ?? String(i),
    value: v,
  })),
)

const growthColumns = computed<Column[]>(() =>
  (lib.data?.photos.growth ?? []).map((g) => ({ label: fmtMonth(g.month), value: g.total })),
)

const TYPE_LABELS: Record<string, string> = {
  photo: '照片',
  video: '视频',
  live: '实况照片',
  other: '其他',
}

const typeItems = computed<BarItem[]>(() => {
  const t = lib.data?.photos.by_type
  if (!t) return []
  return (Object.keys(TYPE_LABELS) as Array<keyof typeof t>)
    .map((k) => ({ key: k, label: TYPE_LABELS[k], value: t[k] ?? 0 }))
    .filter((i) => i.value > 0)
})

function spaceLabel(space: string): string {
  if (space === 'personal') return '个人空间'
  if (space === 'shared') return '共享空间'
  return space
}

const spaceItems = computed<BarItem[]>(() =>
  Object.entries(lib.data?.photos.by_space ?? {}).map(([k, v]) => ({
    key: k,
    label: spaceLabel(k),
    value: v,
  })),
)

const faceItems = computed<BarItem[]>(() => {
  const f = lib.data?.faces
  if (!f) return []
  return [
    { key: 'tagged', label: '群晖照片已标记', value: f.synology_tagged },
    { key: 'named', label: '……归属已命名人物', value: f.synology_named },
    { key: 'detected', label: 'Synopticon 检出人脸', value: f.detected },
    { key: 'restored', label: '经画质修复增强', value: f.restored },
  ]
})

const perPhotoColumns = computed<Column[]>(() =>
  (lib.data?.faces.per_photo ?? []).map((b) => ({
    label: `${b.bucket} 张人脸`,
    axis: b.bucket,
    value: b.photos,
  })),
)

const DETECTOR_LABELS: Record<string, string> = {
  scrfd: '仅 SCRFD 检出',
  yolo: '仅 YOLO 检出',
  merged: '双检测器共同确认',
}

const detectorItems = computed<BarItem[]>(() => {
  const dc = lib.data?.faces.detector_counts ?? {}
  const total = sum(Object.values(dc))
  return Object.entries(dc)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => ({
      key: k,
      label: DETECTOR_LABELS[k] ?? k,
      value: v,
      valueText: `${num(v)} · ${pct(total ? v / total : 0)}`,
    }))
})

const curiosities = computed(() => {
  const f = lib.data?.faces
  if (!f) return []
  const out: Array<{ label: string; value: string; to?: string | null }> = []
  if (f.avg_per_photo != null) out.push({ label: '平均每张照片人脸数', value: f.avg_per_photo.toFixed(2) })
  if (f.most_crowded) {
    out.push({ label: '最拥挤的合影', value: `${num(f.most_crowded.faces)} 张人脸`, to: f.most_crowded.inspect })
  }
  if (f.tiniest) {
    out.push({
      label: '最小人脸',
      value: `${num(f.tiniest.width)} × ${num(f.tiniest.height)} px`,
      to: f.tiniest.inspect,
    })
  }
  if (f.sharpest_eye) {
    out.push({
      label: '最高置信度检测',
      value: `置信度 ${(f.sharpest_eye.det_score * 100).toFixed(1)}%`,
      to: f.sharpest_eye.inspect,
    })
  }
  return out
})

const peopleItems = computed<BarItem[]>(() =>
  (lib.data?.people.distribution ?? []).map((d) => ({
    key: `${d.space}:${d.person_id}`,
    label: d.name,
    href: d.person_url ?? undefined,
    value: d.faces,
    valueText: `${num(d.faces)} · ${pct(d.share)}`,
  })),
)

/** One full-width bar of every tagged face, so the named people's bars can scale to the top person. */
const peopleWhole = computed(() => {
  const p = lib.data?.people
  const tagged = lib.data?.faces.synology_tagged ?? 0
  if (!p || !tagged) return null
  const shown = p.distribution.length
  const top = p.distribution.reduce((sum, d) => sum + d.faces, 0)
  const segments: BarSegment[] = [
    { value: top, tone: 'data', label: `前 ${shown} 位` },
    {
      value: p.everyone_else.faces,
      tone: 'rest',
      label: `其余人物（${num(p.everyone_else.people)} 位）`,
    },
    { value: p.unnamed_or_unlisted_faces, tone: 'faint', label: '未命名或未列出' },
  ]
  const item: BarItem = {
    key: 'whole',
    label: '全部已标记人脸',
    value: tagged,
    valueText: num(tagged),
    segments,
  }
  const legend = segments
    .filter((seg) => seg.value > 0)
    .map((seg) => ({ tone: seg.tone, label: `${seg.label} · ${pct(seg.value / tagged)}` }))
  return { items: [item], legend }
})

const concentration = computed(() => {
  const g = lib.data?.people.gini
  if (g == null) return ''
  if (g < 0.35) return '人脸在各位人物之间分布比较均匀。'
  if (g < 0.6) return '少数几位人物的出镜率明显高于其他人。'
  return '图库中绝大多数人脸集中在极少数人物身上。'
})

const groupingRows = computed(() => {
  const g = lib.data?.grouping
  if (!g) return []
  return [
    { label: '人脸分组数', value: num(g.clusters) },
    { label: '最大分组', value: `${num(g.largest)} 张人脸` },
    { label: '单人脸分组', value: num(g.singletons) },
    { label: '已匹配人物', value: num(g.mapped) },
    { label: '尚未匹配', value: num(g.unmapped) },
  ]
})
</script>

<template>
  <div class="page stats-page">
    <!-- ================= What Synopticon has done ================= -->
    <section class="stats-section" aria-labelledby="life-h" :class="{ refreshing: life.loading && life.data }">
      <header class="section-head">
        <h2 id="life-h">Synopticon 运行统计</h2>
        <p v-if="life.data?.tracking_since" class="muted">
          自 {{ fmtDate(life.data.tracking_since) }} 起统计
        </p>
      </header>

      <div v-if="!life.data && life.loading" class="tiles" aria-busy="true">
        <div v-for="i in 6" :key="i" class="skeleton tile-skel"></div>
      </div>

      <div v-else-if="!life.data && life.error" class="card">
        <p class="muted">无法加载统计数据：{{ life.error }}</p>
        <button type="button" class="btn btn-sm" @click="loadLife">重试</button>
      </div>

      <div v-else-if="lifeEmpty" class="card empty-card">
        <h3>暂无运行记录</h3>
        <p class="muted">
          Synopticon 会记录每次执行的任务以及写回群晖 NAS 的每一项修改。前往「处理流程」页面运行一次「同步图库」后，这里就会显示统计数据。
        </p>
        <div class="cta-row">
          <RouterLink class="btn btn-action" to="/pipeline">前往处理流程</RouterLink>
        </div>
      </div>

      <template v-else-if="life.data">
        <ul v-if="lifeFacts.length" class="facts card">
          <li v-for="f in lifeFacts" :key="f.key">
            <template v-for="(p, i) in f.parts" :key="i">
              <RouterLink v-if="p.to" :to="p.to" class="fact-strong">{{ p.text }}</RouterLink>
              <a v-else-if="p.href" :href="p.href" target="_blank" rel="noopener" class="fact-strong">{{
                p.text
              }}</a>
              <strong v-else-if="p.strong" class="fact-strong">{{ p.text }}</strong>
              <span v-else>{{ p.text }}</span>
            </template>
          </li>
        </ul>

        <div class="tiles">
          <StatTile v-for="t in lifeTiles" :key="t.label" :label="t.label" :value="t.value" :sub="t.sub" />
        </div>

        <div class="two-col">
          <section class="card">
            <h3>按操作统计运行次数</h3>
            <BarList
              v-if="runItems.length"
              :items="runItems"
              :legend="runLegend"
              label="按操作与结果统计的运行次数"
            />
            <p v-else class="muted">暂无运行记录。</p>

            <h4 class="sub-head">触发来源</h4>
            <BarList :items="originItems" label="任务触发来源" />
          </section>

          <section class="card">
            <h3>已写回群晖 NAS</h3>
            <template v-if="life.data.nas.writes_ok + life.data.nas.writes_failed > 0">
              <dl class="kv kv-grid">
                <div v-for="h in nasHighlights" :key="h.label">
                  <dt>{{ h.label }}</dt>
                  <dd>{{ num(h.value) }}</dd>
                </div>
              </dl>
              <h4 class="sub-head">按操作类型分布</h4>
              <BarList
                :items="nasItems"
                :legend="
                  life.data.nas.writes_failed
                    ? [
                        { tone: 'data', label: '成功' },
                        { tone: 'bad', label: '失败' },
                      ]
                    : undefined
                "
                label="按类型统计的群晖修改"
              />
            </template>
            <p v-else class="muted">
              尚未向群晖写入任何修改——在「写回群晖」之前的所有步骤都只读取数据。
              <template v-if="life.data.nas.dry_runs">
                目前已执行 {{ num(life.data.nas.dry_runs) }} 次预演。
              </template>
            </p>
          </section>

          <section class="card">
            <h3>后台处理累计</h3>
            <p class="muted card-lede">历史累计总量（包含重复扫描）。</p>
            <dl class="kv">
              <div v-for="w in workRows" :key="w.label">
                <dt>{{ w.label }}</dt>
                <dd>{{ num(w.value) }}</dd>
              </div>
            </dl>
          </section>

          <section class="card">
            <h3>人脸审核记录</h3>
            <template v-if="life.data.review.decided > 0">
              <BarList :items="reviewItems" label="人脸审核决定" />
              <p v-if="life.data.review.approval_rate != null" class="muted card-foot">
                共完成 {{ num(life.data.review.decided) }} 条审核决定，识别建议通过率为
                {{ pct(life.data.review.approval_rate) }}。
              </p>
            </template>
            <p v-else class="muted">
              暂无审核记录。完成人脸聚类分组后，识别建议会出现在<RouterLink to="/review">人脸审核</RouterLink>页面。
            </p>
          </section>
        </div>
      </template>
    </section>

    <!-- ======================== Your library ======================== -->
    <section class="stats-section" aria-labelledby="lib-h" :class="{ refreshing: lib.loading && lib.data }">
      <header class="section-head">
        <h2 id="lib-h">你的照片图库</h2>
        <p v-if="lib.data" class="muted">统计时间：{{ new Date(lib.data.computed_at * 1000).toLocaleString('zh-CN') }}</p>
      </header>

      <div v-if="!lib.data && lib.loading" aria-busy="true">
        <div class="tiles">
          <div v-for="i in 6" :key="i" class="skeleton tile-skel"></div>
        </div>
        <div class="skeleton chart-skel"></div>
      </div>

      <div v-else-if="!lib.data && lib.error" class="card">
        <p class="muted">无法加载图库统计：{{ lib.error }}</p>
        <button type="button" class="btn btn-sm" @click="loadLib">重试</button>
      </div>

      <div v-else-if="libEmpty" class="card empty-card">
        <h3>尚未同步照片</h3>
        <p class="muted">
          从群晖 NAS 同步图库后，这里就会揭晓你相册里的“头号主角”以及更多图库洞察。
        </p>
        <div class="cta-row">
          <RouterLink class="btn btn-action" to="/pipeline">开始首次同步</RouterLink>
        </div>
      </div>

      <template v-else-if="lib.data">
        <ul v-if="libFacts.length" class="facts card">
          <li v-for="f in libFacts" :key="f.key">
            <template v-for="(p, i) in f.parts" :key="i">
              <RouterLink v-if="p.to" :to="p.to" class="fact-strong">{{ p.text }}</RouterLink>
              <a v-else-if="p.href" :href="p.href" target="_blank" rel="noopener" class="fact-strong">{{
                p.text
              }}</a>
              <strong v-else-if="p.strong" class="fact-strong">{{ p.text }}</strong>
              <span v-else>{{ p.text }}</span>
            </template>
          </li>
        </ul>

        <div class="tiles">
          <StatTile
            v-for="t in libTiles"
            :key="t.label"
            :label="t.label"
            :value="t.value"
            :sub="t.sub"
            :to="t.to"
          />
        </div>

        <h3 class="group-head">照片分布</h3>
        <section class="card">
          <h3>按年份统计</h3>
          <p class="muted card-lede">按照片实际拍摄日期统计。</p>
          <ColumnChart :columns="yearColumns" label="按年份统计照片数" unit="张" />
        </section>

        <div class="two-col">
          <section class="card">
            <h3>拍摄时段分布</h3>
            <p class="muted card-lede">按拍摄小时分布。</p>
            <ColumnChart :columns="hourColumns" label="按小时统计照片数" unit="张" />
          </section>
          <section class="card">
            <h3>星期分布</h3>
            <p class="muted card-lede">按拍摄星期分布。</p>
            <ColumnChart :columns="weekdayColumns" label="按星期统计照片数" unit="张" />
          </section>
        </div>

        <div class="two-col">
          <section class="card">
            <h3>图库增长趋势</h3>
            <p class="muted card-lede">按添加时间统计群晖照片图库的累计规模变化。</p>
            <ColumnChart
              :columns="growthColumns"
              variant="area"
              highlight="last"
              label="图库随时间的规模增长"
              unit="张"
            />
          </section>
          <section class="card">
            <h3>图库构成</h3>
            <BarList v-if="typeItems.length" :items="typeItems" label="按文件类型统计" />
            <p v-else class="muted">暂无文件类型记录。</p>
            <template v-if="spaceItems.length > 1">
              <h4 class="sub-head">按空间分布</h4>
              <BarList :items="spaceItems" label="按空间统计" />
            </template>
          </section>
        </div>

        <h3 class="group-head">人脸分析</h3>
        <div class="two-col">
          <section class="card">
            <h3>图库中的人脸</h3>
            <BarList :items="faceItems" label="人脸数量统计" />
            <dl v-if="curiosities.length" class="kv curiosities">
              <div v-for="c in curiosities" :key="c.label">
                <dt>{{ c.label }}</dt>
                <dd>
                  <RouterLink v-if="c.to" :to="c.to">{{ c.value }}</RouterLink>
                  <template v-else>{{ c.value }}</template>
                </dd>
              </div>
            </dl>
          </section>

          <section class="card">
            <h3>单张照片人脸数分布</h3>
            <template v-if="lib.data.faces.photos_scanned > 0">
              <p class="muted card-lede">
                基于已扫描的 {{ num(lib.data.faces.photos_scanned) }} 张照片。
              </p>
              <ColumnChart
                :columns="perPhotoColumns"
                label="按人脸数量统计照片数"
                unit="张"
              />
              <template v-if="detectorItems.length">
                <h4 class="sub-head">检测器贡献分布</h4>
                <BarList :items="detectorItems" label="按检测器统计人脸" />
              </template>
            </template>
            <p v-else class="muted">
              尚未进行人脸检测。请前往<RouterLink to="/pipeline">处理流程</RouterLink>页面运行<strong>人脸检测与提取</strong>。
            </p>
          </section>
        </div>

        <h3 class="group-head">人物分布</h3>
        <section class="card">
          <h3>出镜最多的人物</h3>
          <template v-if="lib.data.faces.synology_tagged > 0">
            <p class="muted card-lede">
              占群晖照片全部已标记人脸的比例，涵盖
              {{ num(lib.data.people.listed_named) }} 位已命名人物。
            </p>
            <BarList
              v-if="peopleWhole"
              class="people-whole"
              :items="peopleWhole.items"
              :legend="peopleWhole.legend"
              label="全部已标记人脸的归属占比"
            />
            <BarList :items="peopleItems" label="各人物已标记人脸数" />
            <dl class="kv kv-grid people-facts">
              <div v-if="lib.data.people.listed_named >= 10">
                <dt>前 10 位人物占比</dt>
                <dd>{{ pct(lib.data.people.top10_share) }}</dd>
              </div>
              <div>
                <dt>仅含 1 张人脸的已命名人物</dt>
                <dd>{{ num(lib.data.people.one_face_people) }}</dd>
              </div>
              <div v-if="lib.data.people.hidden">
                <dt>群晖中已隐藏的人物</dt>
                <dd>{{ num(lib.data.people.hidden) }}</dd>
              </div>
            </dl>
            <p
              v-if="concentration"
              class="muted card-foot"
              :title="`基尼系数 ${lib.data.people.gini?.toFixed(2)}`"
            >
              {{ concentration }}
            </p>
          </template>
          <p v-else class="muted">群晖照片尚未标记任何人脸。</p>
        </section>

        <section class="card">
          <h3>最近一次人脸聚类分组</h3>
          <template v-if="lib.data.grouping">
            <p class="muted card-lede">
              第 #{{ lib.data.grouping.run_id }} 次聚类 · {{ ago(lib.data.grouping.created_at) }}
            </p>
            <dl class="kv kv-grid">
              <div v-for="g in groupingRows" :key="g.label">
                <dt>{{ g.label }}</dt>
                <dd>{{ g.value }}</dd>
              </div>
            </dl>
          </template>
          <p v-else class="muted">
            尚未进行聚类分组。完成人脸检测后，请前往<RouterLink to="/pipeline">处理流程</RouterLink>页面运行<strong>人脸聚类分组</strong>。
          </p>
        </section>
      </template>
    </section>
  </div>
</template>

<style scoped>
.stats-section {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  transition: opacity 0.15s;
}
.stats-section + .stats-section {
  margin-top: var(--sp-6);
}
.stats-section.refreshing {
  opacity: 0.6;
}
.section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-1) var(--sp-3);
}
.section-head h2,
.section-head p {
  margin: 0;
}
.group-head {
  margin: var(--sp-2) 0 0;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-2);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.tiles {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 150px), 1fr));
  gap: var(--sp-3);
}
.tiles :deep(.tile-value) {
  white-space: nowrap;
}
.tile-skel {
  height: 92px;
  border-radius: var(--radius-lg);
}
.chart-skel {
  height: 220px;
  margin-top: var(--sp-4);
  border-radius: var(--radius-lg);
}
.two-col {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 380px), 1fr));
  gap: var(--sp-4);
  align-items: start;
}
.card {
  min-width: 0;
}
.card-lede {
  margin: calc(-1 * var(--sp-2)) 0 var(--sp-3);
}
.card-foot {
  margin: var(--sp-3) 0 0;
}
.sub-head {
  margin: var(--sp-4) 0 var(--sp-2);
  font-size: var(--fs-base);
  font-weight: 600;
  color: var(--text-2);
}
.empty-card {
  max-width: 640px;
}
.facts {
  list-style: none;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr));
  gap: var(--sp-3) var(--sp-5);
  font-size: var(--fs-lg);
  line-height: 1.4;
}
.facts li {
  min-width: 0;
  overflow-wrap: anywhere;
}
.fact-strong {
  font-weight: 600;
}
strong.fact-strong {
  color: var(--text);
}
.kv {
  margin: 0;
  display: flex;
  flex-direction: column;
}
.kv > div {
  display: flex;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: 6px 0;
  border-bottom: 1px solid var(--border-soft);
}
.kv > div:last-child {
  border-bottom: none;
}
.kv dt {
  color: var(--text-2);
  min-width: 0;
}
.kv dd {
  margin: 0;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  text-align: right;
  white-space: nowrap;
}
.kv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 150px), 1fr));
  gap: var(--sp-3);
}
.kv-grid > div {
  flex-direction: column;
  justify-content: flex-start;
  gap: 2px;
  padding: 0;
  border-bottom: none;
}
.kv-grid dt {
  font-size: var(--fs-sm);
}
.kv-grid dd {
  text-align: left;
  font-size: var(--fs-xl);
}
.curiosities {
  margin-top: var(--sp-4);
}
.people-facts {
  margin-top: var(--sp-4);
}
.people-whole {
  margin-bottom: var(--sp-4);
  padding-bottom: var(--sp-3);
  border-bottom: 1px solid var(--border-soft);
}

@media (max-width: 560px) {
  .page.stats-page {
    padding: var(--sp-3);
  }
  .facts {
    font-size: var(--fs-base);
  }
  .tiles :deep(.tile-value) {
    font-size: 22px;
  }
}
</style>
