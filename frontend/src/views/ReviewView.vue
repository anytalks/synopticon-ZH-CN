<script setup lang="ts">
// Review queue — the behaviour-dense port of review.js + review.html.j2 + the
// review_card Jinja macro. ReviewView owns the single reactive items array; Grid
// and Focus are two projections over it (the old dual-DOM / clone hack dies).
//
// Owns: items[] + total + a session-local decision per item; kind/status filters
// and the two "hide unnamed" toggles; the grid|focus view (persisted to
// localStorage "reviewView" and the ?view=focus query param, dropped for grid);
// offset infinite scroll (page size 100); a session-local undo stack (u);
// keyboard flow y/n/s/j/k + ←/→ in focus; suggested-name editing; and refreshing
// the pending counts after mutations.
//
// Selection is tracked by item id (not index) so it survives list mutations the
// way review.js's .sel-by-identity did: a mouse decide on a non-selected card
// leaves the highlight put; a decide on the current card advances; undo re-homes
// the selection onto the restored card. `currentItem` falls forward past a
// decided/filtered selection, exactly like review.js currentCard().
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getJSON, postJSON } from '../api/client'
import { toast } from '../stores/toasts'
import type {
  ClientReviewItem,
  RetargetResponse,
  ReviewCounts,
  ReviewDecision,
  ReviewItem,
  ReviewItemsResponse,
  ReviewPersonSuggestion,
} from '../api/types'
import ReviewGrid from '../components/review/ReviewGrid.vue'
import ReviewFocus from '../components/review/ReviewFocus.vue'
import BulkApproveBar from '../components/review/BulkApproveBar.vue'
import PersonPickerDialog from '../components/review/PersonPickerDialog.vue'
import { useKeyboard } from '../composables/useKeyboard'

const PAGE_SIZE = 100
const KINDS = ['', 'assign', 'low_confidence', 'reassign', 'merge', 'merge_named', 'new_person']
const STATUSES = ['pending', 'approved', 'rejected', 'hidden', 'applied', 'failed']
const KIND_LABELS: Record<string, string> = {
  '': '全部类型',
  assign: '归属认领',
  low_confidence: '低置信度复核',
  reassign: '改判人物',
  merge: '合并未命名分组',
  merge_named: '合并已命名人物',
  new_person: '发现新人物',
}
const STATUS_LABELS: Record<string, string> = {
  pending: '待审核',
  approved: '已通过',
  rejected: '已拒绝',
  hidden: '已隐藏',
  applied: '已写回',
  failed: '写回失败',
}
const PREFETCH_MARGIN = 20 // focus: prefetch when within N of the loaded tail

const route = useRoute()
const router = useRouter()

function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}

// -- filters / view (initialised from the route query + localStorage) -------- #
function sanitizeKind(v: unknown): string {
  return typeof v === 'string' && KINDS.includes(v) ? v : ''
}
function sanitizeStatus(v: unknown): string {
  return typeof v === 'string' && STATUSES.includes(v) ? v : 'pending'
}
function resolveInitialView(): 'grid' | 'focus' {
  const q = route.query.view
  if (q === 'focus' || q === 'grid') return q
  try {
    const ls = localStorage.getItem('reviewView')
    if (ls === 'focus' || ls === 'grid') return ls
  } catch {
    /* localStorage unavailable */
  }
  return 'grid'
}

const kind = ref(sanitizeKind(route.query.kind))
const status = ref(sanitizeStatus(route.query.status))
const view = ref<'grid' | 'focus'>(resolveInitialView())
const hideUnnamed = ref(readFlag('hideUnnamed'))
const hideUnnamedMerges = ref(readFlag('hideUnnamedMerges'))
const legendOpen = ref(false)

function readFlag(key: string): boolean {
  try {
    return !!localStorage.getItem(key)
  } catch {
    return false
  }
}
function writeFlag(key: string, on: boolean): void {
  try {
    if (on) localStorage.setItem(key, '1')
    else localStorage.removeItem(key)
  } catch {
    /* ignore */
  }
}

// -- items + pagination ------------------------------------------------------ #
const items = ref<ClientReviewItem[]>([])
const total = ref(0)
const loading = ref(false)
const exhausted = ref(false)
const selectedId = ref<number | null>(null)
const undoStack = ref<{ id: number; decision: ReviewDecision; kind: string }[]>([])
const counts = ref<ReviewCounts>({})

const loaded = computed(() => items.value.length)
const pendingCount = computed(() =>
  Object.values(counts.value.pending ?? {}).reduce((a, b) => a + b, 0),
)

// Items shown in the grid / carousel (filtered by the two "hide unnamed"
// toggles). Filtered-out items are simply not rendered — equivalent to the old
// body-class display:none, but reactive.
const renderedItems = computed(() =>
  items.value.filter((it) => {
    if (hideUnnamed.value && it.unnamed_target) return false
    if (hideUnnamedMerges.value && it.unnamed_merge) return false
    return true
  }),
)
// Navigable = rendered and not yet decided this session (review.js cardVisible).
const navigable = computed(() => renderedItems.value.filter((it) => !it.decision))

function navIndexOf(id: number | null): number {
  return id == null ? -1 : navigable.value.findIndex((it) => it.item_id === id)
}

// The current card: the selected navigable item, else the next navigable item
// after the selected position (fall-forward past a decided/filtered selection),
// else the first navigable item. Mirrors review.js currentCard().
const currentItem = computed<ClientReviewItem | null>(() => {
  const nav = navigable.value
  if (!nav.length) return null
  const i = navIndexOf(selectedId.value)
  if (i >= 0) return nav[i]
  const all = renderedItems.value
  const pos = all.findIndex((it) => it.item_id === selectedId.value)
  if (pos >= 0) {
    for (let j = pos + 1; j < all.length; j++) {
      if (!all[j].decision) return all[j]
    }
  }
  return nav[0]
})

function currentNavIndex(): number {
  const cur = currentItem.value
  return cur ? navIndexOf(cur.item_id) : -1
}

// Select the navigable item at `i` (clamped). Empty -> clears selection.
function select(i: number): void {
  const nav = navigable.value
  if (!nav.length) {
    selectedId.value = null
    return
  }
  const idx = Math.max(0, Math.min(i, nav.length - 1))
  selectedId.value = nav[idx].item_id
}

// -- data loading ------------------------------------------------------------ #
async function loadMore(): Promise<void> {
  if (loading.value || exhausted.value) return
  loading.value = true
  try {
    const url =
      `/api/review/items?kind=${encodeURIComponent(kind.value)}` +
      `&status=${encodeURIComponent(status.value)}` +
      `&limit=${PAGE_SIZE}&offset=${items.value.length}`
    const res = await getJSON<ReviewItemsResponse>(url)
    total.value = res.total
    const mapped: ClientReviewItem[] = (res.items || []).map((it: ReviewItem) => ({
      ...it,
      decision: null,
    }))
    items.value.push(...mapped)
    if (!res.items || !res.items.length || items.value.length >= total.value) {
      exhausted.value = true
    }
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    loading.value = false
  }
  if (view.value === 'focus') maybePrefetch()
}

async function reload(): Promise<void> {
  items.value = []
  total.value = 0
  exhausted.value = false
  selectedId.value = null
  undoStack.value = []
  await loadMore()
  select(0)
}

async function refreshCounts(): Promise<void> {
  try {
    const res = await getJSON<{ counts: ReviewCounts }>('/api/review/counts')
    counts.value = res.counts
  } catch {
    /* non-fatal */
  }
}

// Focus prefetch: the grid sentinel isn't mounted here, so drive loadMore() from
// the current position within the full loaded list (review.js maybePrefetch).
function maybePrefetch(): void {
  if (view.value !== 'focus' || exhausted.value || loading.value) return
  const cur = currentItem.value
  const pos = cur
    ? items.value.findIndex((it) => it.item_id === cur.item_id)
    : items.value.length - 1
  if (pos >= 0 && items.value.length - pos <= PREFETCH_MARGIN) void loadMore()
}

// -- decisions --------------------------------------------------------------- #
const DECISION_VERB: Record<ReviewDecision, string> = {
  approve: '通过',
  reject: '拒绝',
  hide: '隐藏',
}

async function decide(
  item: ClientReviewItem,
  decision: ReviewDecision,
  advance: boolean,
): Promise<void> {
  // Capture the navigable slot before the decision drops it from `navigable`,
  // so select(idx) lands on the item that takes its place.
  const idx = advance ? currentNavIndex() : -1
  try {
    await postJSON(`/api/review/${item.item_id}/decide`, { decision })
    item.decision = decision
    undoStack.value.push({ id: item.item_id, decision, kind: item.kind })
    if (advance) select(idx)
    if (view.value === 'focus') maybePrefetch()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function undo(): Promise<void> {
  const last = undoStack.value.pop()
  if (!last) {
    toast('没有可撤销的操作')
    return
  }
  try {
    await postJSON(`/api/review/${last.id}/decide`, { decision: 'undo' })
    const item = items.value.find((it) => it.item_id === last.id)
    if (item) item.decision = null
    const kindLabel = KIND_LABELS[last.kind] ?? last.kind
    toast(`已撤销对「${kindLabel}」#${last.id} 的${DECISION_VERB[last.decision]}操作`)
    if (item) select(navIndexOf(item.item_id))
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

// -- retargeting ------------------------------------------------------------- #
// The picker rewrites the queue only; the NAS write still happens later through
// Apply. A retarget is not pushed onto the undo stack: a merge creates one
// approved assign row per face, and undoing the source row would orphan them.
const picker = ref<{ item: ClientReviewItem; mode: 'merge' | 'reassign' } | null>(null)
const retargeting = ref(false)

const RETARGET_DECISION: Record<string, ReviewDecision> = {
  approved: 'approve',
  hidden: 'hide',
}

function openPicker(item: ClientReviewItem, mode: 'merge' | 'reassign'): void {
  picker.value = { item, mode }
}

// The picker takes a described source rather than an item, so Inspect can point
// it at a bare face. A new_person group has no space of its own — the target's
// decides which of its faces can be tagged — so only a reassign pins one.
const pickerLabel = computed(() => {
  const open = picker.value
  if (!open) return ''
  if (open.mode === 'merge') {
    const n = Number(open.item.payload.size ?? open.item.new_person_crops.length) || 0
    return `${n} 张人脸`
  }
  return String(open.item.payload.person_name || open.item.payload.person_id || '未命名人物')
})
const pickerCrops = computed(() => {
  const open = picker.value
  if (!open) return []
  return open.mode === 'merge' ? open.item.new_person_crops : [open.item.crop]
})
const pickerSpace = computed(() =>
  picker.value && picker.value.mode !== 'merge'
    ? String(picker.value.item.payload.space || '')
    : '',
)

async function onPickerConfirm(target: ReviewPersonSuggestion): Promise<void> {
  const open = picker.value
  if (!open || retargeting.value) return
  const { item, mode } = open
  // The item leaves `navigable` the moment it gets a decision; remember its slot
  // so the selection lands on whatever takes its place (same trick as decide()).
  const idx = navIndexOf(item.item_id)
  retargeting.value = true
  try {
    const res = await postJSON<RetargetResponse>(
      `/api/review/${item.item_id}/retarget`,
      {
        space: target.space,
        person_id: target.person_id,
        person_name: target.name,
      },
    )
    item.decision = RETARGET_DECISION[res.status] ?? 'approve'
    item.payload.person_id = res.person_id
    item.payload.person_name = res.person_name
    item.payload.manual_target = true
    picker.value = null
    if (mode === 'merge') {
      toast(
        `已加入待写回队列：${res.created} 张人脸将标记为 ${target.name}` +
          (res.skipped ? ` · 跳过 ${res.skipped} 张` : ''),
        'ok',
      )
    } else {
      toast(`已改判为 ${target.name}`, 'ok')
    }
    if (idx >= 0) select(idx)
    void refreshCounts()
    if (view.value === 'focus') maybePrefetch()
  } catch (e) {
    toast(errMsg(e), 'error')
  } finally {
    retargeting.value = false
  }
}

async function setName(item: ClientReviewItem, value: string): Promise<void> {
  try {
    await postJSON(`/api/review/${item.item_id}/name`, { name: value })
    item.payload.suggested_name = value
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function onBulkApprove(payload: {
  kind: string
  minConfidence: number
}): Promise<void> {
  try {
    const res = await postJSON<{ approved: number }>('/api/review/bulk', {
      kind: payload.kind,
      min_confidence: payload.minConfidence,
    })
    toast(`已批量通过 ${res.approved} 条建议`)
    await reload()
    void refreshCounts()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

async function onBulkApproveAll(payload: { kind: string }): Promise<void> {
  try {
    const res = await postJSON<{ approved: number }>('/api/review/bulk-all', {
      kind: payload.kind,
    })
    toast(`已一键通过 ${res.approved} 条待审核建议`, 'ok')
    await reload()
    void refreshCounts()
  } catch (e) {
    toast(errMsg(e), 'error')
  }
}

const canUndo = computed(() => undoStack.value.length > 0)
const undoTitle = computed(() => {
  const last = undoStack.value[undoStack.value.length - 1]
  return last
    ? `撤销对「${KIND_LABELS[last.kind] ?? last.kind}」#${last.id} 的${DECISION_VERB[last.decision]}操作`
    : '没有可撤销的操作'
})

// Focus empty-state message (review.js emptyMessage): considers every loaded
// item so it can distinguish "all filtered out" from "all decided".
const emptyMessage = computed(() => {
  if (!exhausted.value) return '加载中…'
  const all = items.value
  if (!all.length) return '暂无待审核内容。'
  if (all.some((it) => !it.decision))
    return '其余条目已被当前筛选条件隐藏。'
  return '已到达队列末尾，所有已加载条目均已处理完毕。'
})

// -- view / filter wiring ---------------------------------------------------- #
function syncQuery(): void {
  const q: Record<string, string> = {}
  if (kind.value) q.kind = kind.value
  if (status.value && status.value !== 'pending') q.status = status.value
  if (view.value === 'focus') q.view = 'focus'
  void router.replace({ query: q })
}

function applyFilters(): void {
  syncQuery()
  void reload().then(refreshCounts)
}

function setView(v: 'grid' | 'focus'): void {
  view.value = v === 'focus' ? 'focus' : 'grid'
}

watch(view, (v) => {
  // Persist the choice: ?view=focus in the URL and localStorage; grid is the
  // default, so it clears both (matching review.js setView()).
  try {
    if (v === 'grid') localStorage.removeItem('reviewView')
    else localStorage.setItem('reviewView', v)
  } catch {
    /* ignore */
  }
  syncQuery()
  if (v === 'focus') maybePrefetch()
})

watch([hideUnnamed, hideUnnamedMerges], () => {
  writeFlag('hideUnnamed', hideUnnamed.value)
  writeFlag('hideUnnamedMerges', hideUnnamedMerges.value)
  select(0)
})

// Re-home selection / prefetch when focus resolves a new current item.
watch(currentItem, () => {
  if (view.value === 'focus') maybePrefetch()
})

// -- keyboard ---------------------------------------------------------------- #
useKeyboard((e) => {
  if (e.key === 'u') {
    void undo()
    return
  }
  if (!navigable.value.length) return
  const cur = currentItem.value
  const idx = currentNavIndex()
  if (e.key === 'y' && cur) void decide(cur, 'approve', true)
  else if (e.key === 'n' && cur) void decide(cur, 'reject', true)
  // Kind-specific corrections: hide/merge a suggested new person, reassign a
  // face the pipeline aimed at the wrong person. No-ops on other kinds.
  else if (e.key === 'h' && cur?.kind === 'new_person') void decide(cur, 'hide', true)
  else if (e.key === 'm' && cur?.kind === 'new_person') openPicker(cur, 'merge')
  else if (e.key === 'r' && (cur?.kind === 'assign' || cur?.kind === 'low_confidence'))
    openPicker(cur, 'reassign')
  else if (e.key === 's') select(idx + 1)
  else if (e.key === 'j') select(idx + 1)
  else if (e.key === 'k') select(idx - 1)
  else if (view.value === 'focus' && e.key === 'ArrowLeft') {
    e.preventDefault()
    select(idx - 1)
  } else if (view.value === 'focus' && e.key === 'ArrowRight') {
    e.preventDefault()
    select(idx + 1)
  }
})

// Carousel thumb click: select it only if it is currently navigable.
function onSelectItem(item: ClientReviewItem): void {
  const i = navIndexOf(item.item_id)
  if (i >= 0) select(i)
}

onMounted(async () => {
  await reload()
  void refreshCounts()
})
</script>

<template>
  <div class="page review-page" id="review-page">
    <div class="toolbar" role="region" aria-label="审核控制栏">
      <div class="toolbar-row">
        <div class="filters">
          <label for="f-kind">
            <span class="muted">建议类型</span>
            <select
              name="kind"
              id="f-kind"
              class="select"
              v-model="kind"
              @change="applyFilters"
            >
              <option v-for="k in KINDS" :key="k" :value="k">{{ KIND_LABELS[k] ?? k }}</option>
            </select>
          </label>
          <label for="f-status">
            <span class="muted">状态</span>
            <select
              name="status"
              id="f-status"
              class="select"
              v-model="status"
              @change="applyFilters"
            >
              <option v-for="s in STATUSES" :key="s" :value="s">{{ STATUS_LABELS[s] ?? s }}</option>
            </select>
          </label>
          <button type="button" class="btn btn-action btn-filter" @click="applyFilters">筛选</button>
        </div>
        <div class="toolbar-sep"></div>
        <label for="f-view">
          <span class="muted">视图</span>
          <div class="seg" role="group" aria-label="审核布局">
            <button
              type="button"
              class="seg-btn"
              data-view="grid"
              :aria-pressed="view !== 'focus'"
              @click="setView('grid')"
            >
              网格
            </button>
            <button
              type="button"
              class="seg-btn"
              data-view="focus"
              :aria-pressed="view === 'focus'"
              @click="setView('focus')"
            >
              专注
            </button>
          </div>
        </label>
        <div class="toolbar-sep"></div>
        <div class="toolbar-spacer"></div>
        <span class="loaded-count" id="loaded-count" aria-live="polite">
          已加载 {{ loaded }} / {{ total }} 条<template v-if="pendingCount">
            · {{ pendingCount }} 条待审核</template
          >
        </span>
        <BulkApproveBar
          :kind="kind"
          :pending-by-kind="counts.pending ?? {}"
          @approve="onBulkApprove"
          @approve-all="onBulkApproveAll"
        />
        <button
          class="btn btn-sm btn-ghost"
          type="button"
          id="undo-btn"
          :disabled="!canUndo"
          :title="undoTitle"
          @click="undo"
        >
          撤销 <kbd>u</kbd>
        </button>
        <button
          class="btn btn-sm btn-ghost"
          type="button"
          aria-haspopup="dialog"
          @click="legendOpen = !legendOpen"
        >
          快捷键
        </button>
      </div>

      <div class="toolbar-row">
        <label
          class="check muted"
          title="隐藏目标人物尚未命名的归属认领、低置信度复核和改判人物建议"
        >
          隐藏未命名目标
          <input type="checkbox" v-model="hideUnnamed" /> 
        </label>
        <label class="check muted">
          隐藏未命名分组间合并
          <input type="checkbox" v-model="hideUnnamedMerges" /> 
        </label>
      </div>
    </div>

    <ReviewFocus
      v-if="view === 'focus'"
      :items="renderedItems"
      :current-id="currentItem ? currentItem.item_id : null"
      :empty-message="emptyMessage"
      :loading="loading"
      @decide="(pl) => decide(pl.item, pl.decision, true)"
      @name="(pl) => setName(pl.item, pl.value)"
      @retarget="(pl) => openPicker(pl.item, pl.mode)"
      @select="onSelectItem"
    />
    <ReviewGrid
      v-else
      :items="renderedItems"
      :selected-id="selectedId"
      :exhausted="exhausted"
      :loading="loading"
      @decide="(pl) => decide(pl.item, pl.decision, false)"
      @name="(pl) => setName(pl.item, pl.value)"
      @retarget="(pl) => openPicker(pl.item, pl.mode)"
      @select="onSelectItem"
      @load-more="loadMore"
    />
  </div>

  <PersonPickerDialog
    v-if="picker"
    :mode="picker.mode"
    :source-label="pickerLabel"
    :source-crops="pickerCrops"
    :space="pickerSpace"
    :source-key="picker.item.item_id"
    :busy="retargeting"
    @confirm="onPickerConfirm"
    @cancel="picker = null"
  />

  <div
    v-if="legendOpen"
    class="popover"
    role="dialog"
    aria-label="键盘快捷键"
  >
    <h3>键盘快捷键</h3>
    <ul>
      <li><kbd>y</kbd> 通过 · <kbd>n</kbd> 拒绝 · <kbd>s</kbd> 跳过</li>
      <li><kbd>j</kbd> 下一张 · <kbd>k</kbd> 上一张</li>
      <li><kbd>&larr;</kbd> 上一张 · <kbd>&rarr;</kbd> 下一张（专注视图）</li>
      <li><kbd>u</kbd> 撤销上次操作（仅限本次会话）</li>
      <li>
        发现新人物：<kbd>h</kbd> 永久隐藏 · <kbd>m</kbd> 并入已有的人物
      </li>
      <li>
        归属建议：<kbd>r</kbd> 改判给其他人物（不可撤销）
      </li>
    </ul>
    <button class="btn btn-sm" type="button" @click="legendOpen = false">关闭</button>
  </div>
</template>

<style scoped>
.toolbar {
  display: flex;
  flex-flow: column wrap;
  align-items: flex-start;
  gap: var(--sp-2);
  background: var(--bg-raised);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius-lg);
  margin-bottom: var(--sp-3);
  position: sticky;
  top: var(--toolbar-h);
  gap: var(--sp-4);
  z-index: 10;
}
.toolbar-row {
  display: flex;
  flex-flow: row wrap;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  width: 100%;
}
.toolbar-row:not(:first-child) {
  border-top: 1px solid var(--border-soft);
}
.toolbar label {
  display: flex;
  gap: var(--sp-1);
  flex-flow: column nowrap;
}
.toolbar-sep {
  width: 1px;
  height: 60px;
  background: var(--border-soft);
  margin: 0 var(--sp-2);
}
@media (max-width: 640px) {
  .toolbar-sep {
    display: none;
  }
}
.toolbar-spacer {
  flex: 1;
}
.filters {
  display: flex;
  gap: var(--sp-2);
  align-items: center;
}
.loaded-count {
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.btn-filter {
  margin-top: 20px;
}

/* Segmented Grid|Focus control. */
.seg {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.seg-btn {
  border: 0;
  background: var(--bg-raised);
  color: var(--text-2);
  font: inherit;
  font-size: var(--fs-sm);
  padding: var(--sp-1) var(--sp-3);
  cursor: pointer;
}
.seg-btn + .seg-btn {
  border-left: 1px solid var(--border);
}
.seg-btn[aria-pressed='true'] {
  background: var(--sel-tint-strong);
  color: var(--action);
  font-weight: 600;
}

/* Keyboard-shortcut legend, pinned bottom-right. */
.popover {
  position: fixed;
  bottom: var(--sp-5);
  right: var(--sp-5);
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-modal);
  padding: var(--sp-4);
  z-index: 50;
  max-width: 320px;
}
.popover ul {
  margin: var(--sp-2) 0;
  padding-left: var(--sp-4);
}
.popover li {
  margin: var(--sp-1) 0;
}
</style>
