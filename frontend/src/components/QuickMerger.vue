<script setup lang="ts">
// QuickMerger: triage the backlog of unnamed Synology people, one card at a
// time. Writes hit the NAS directly (not the review queue), so the first write of a
// session asks for confirmation once; after that the flow stays uninterrupted.
// The server enforces its own gates regardless: `confirm: true` on every write
// and a hard refusal to merge a person that has a name on the NAS.
import { ref, computed, onBeforeUnmount, nextTick } from 'vue'
import { getJSON, postJSON, ApiError } from '../api/client'
import { toast } from '../stores/toasts'
import { confirm } from '../composables/useConfirm'

interface QmPerson {
  id: number
  space: string
  name: string
  item_count: number | null
  thumb_url: string | null
  link: string | null
}
interface Status {
  spaces: string[]
  nas_configured: boolean
  web_base: string | null
}

// The HIDE_CODE is quickly typeable to prevent interrupting the flow of merging faces quickly
const HIDE_CODE = '11'
const SUGGEST_DEBOUNCE = 300
const SPACE_LABELS: Record<string, string> = {
  personal: '个人空间',
  shared: '共享空间',
}

const status = ref<Status | null>(null)
const space = ref('')
const people = ref<QmPerson[]>([])
const index = ref(0)
const loading = ref(false)
const busy = ref(false)
const loaded = ref(false)

const query = ref('')
const suggestions = ref<QmPerson[]>([])
const selected = ref(-1)
const searching = ref(false)
const inputEl = ref<HTMLInputElement | null>(null)

let armed = false
let debounceTimer: number | null = null
let suggestSeq = 0

const current = computed<QmPerson | null>(() => people.value[index.value] ?? null)
const target = computed<QmPerson | null>(() =>
  selected.value >= 0 ? (suggestions.value[selected.value] ?? null) : null,
)
const done = computed(() => loaded.value && index.value >= people.value.length)

async function loadStatus(): Promise<void> {
  try {
    status.value = await getJSON<Status>('/api/quickmerger/status')
    if (!space.value) space.value = status.value.spaces[0] ?? 'personal'
  } catch (e) {
    toast((e as Error).message || '读取未命名人物速并状态失败', 'error')
  }
}

async function load(refresh = false): Promise<void> {
  if (!space.value) await loadStatus()
  loading.value = true
  try {
    const data = await getJSON<{ persons: QmPerson[] }>(
      `/api/quickmerger/persons?space=${encodeURIComponent(space.value)}` +
        (refresh ? '&refresh=true' : ''),
    )
    people.value = data.persons
    index.value = 0
    loaded.value = true
    resetInput()
    await nextTick()
    inputEl.value?.focus()
  } catch (e) {
    toast((e as Error).message || '加载人物列表失败', 'error')
  } finally {
    loading.value = false
  }
}

function resetInput(): void {
  query.value = ''
  suggestions.value = []
  selected.value = -1
  searching.value = false
  if (debounceTimer !== null) window.clearTimeout(debounceTimer)
  debounceTimer = null
}

function advance(by = 1): void {
  index.value = Math.min(index.value + by, people.value.length)
  resetInput()
  void nextTick(() => inputEl.value?.focus())
}

function back(): void {
  if (index.value === 0) return
  index.value--
  resetInput()
  void nextTick(() => inputEl.value?.focus())
}

/** One confirmation per session before the first NAS write. */
async function arm(): Promise<boolean> {
  if (armed) return true
  const ok = await confirm({
    title: '未命名人物速并会直接写入群晖 NAS',
    message:
      '命名和隐藏操作可以撤销，但将未命名人物合并到已有的人物中不可撤销——被合并的人物将从群晖照片中消失。' +
      '本次会话后续操作不再重复提示。',
    okLabel: '我知道了',
  })
  armed = ok
  return ok
}

function onInput(): void {
  const value = query.value.trim()
  // The userscript's muscle-memory shortcut: typing 11 hides, no Enter needed.
  if (value === HIDE_CODE && selected.value === -1) {
    void hide()
    return
  }
  if (debounceTimer !== null) window.clearTimeout(debounceTimer)
  if (!value) {
    suggestions.value = []
    selected.value = -1
    searching.value = false
    return
  }
  searching.value = true
  debounceTimer = window.setTimeout(() => void search(value), SUGGEST_DEBOUNCE)
}

async function search(prefix: string): Promise<void> {
  const seq = ++suggestSeq
  try {
    const data = await getJSON<{ suggestions: QmPerson[] }>(
      `/api/quickmerger/suggest?space=${encodeURIComponent(space.value)}` +
        `&prefix=${encodeURIComponent(prefix)}`,
    )
    if (seq !== suggestSeq) return // a newer keystroke already won
    suggestions.value = data.suggestions
    selected.value = -1
  } catch (e) {
    if (seq === suggestSeq) {
      suggestions.value = []
      toast((e as Error).message || '搜索候选人物失败', 'error')
    }
  } finally {
    if (seq === suggestSeq) searching.value = false
  }
}

function move(delta: number): void {
  if (!suggestions.value.length) return
  const n = suggestions.value.length
  selected.value = (selected.value + delta + n) % n
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    move(1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    move(-1)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    void submit()
  }
}

async function write<T>(url: string, body: Record<string, unknown>): Promise<T | null> {
  busy.value = true
  try {
    return await postJSON<T>(url, { ...body, confirm: true })
  } catch (e) {
    const msg =
      e instanceof ApiError && typeof e.body?.error === 'string'
        ? e.body.error
        : (e as Error).message || '写入失败'
    toast(msg, 'error')
    return null
  } finally {
    busy.value = false
  }
}

async function submit(): Promise<void> {
  const person = current.value
  if (!person || busy.value) return
  const value = query.value.trim()

  if (value === HIDE_CODE && selected.value === -1) return void hide()
  if (!value && selected.value === -1) return advance()
  if (!(await arm())) return

  if (selected.value !== -1) {
    const into = suggestions.value[selected.value]
    if (!into) return
    const res = await write('/api/quickmerger/merge', {
      space: space.value,
      source_id: person.id,
      target_id: into.id,
    })
    if (res === null) return
    toast(`已将 #${person.id} 合并至 ${into.name}`, 'ok')
  } else {
    const res = await write('/api/quickmerger/name', {
      space: space.value,
      person_id: person.id,
      name: value,
    })
    if (res === null) return
    toast(`已将 #${person.id} 命名为 ${value}`, 'ok')
  }
  advance()
}

async function hide(): Promise<void> {
  const person = current.value
  if (!person || busy.value) return
  if (!(await arm())) return
  const res = await write('/api/quickmerger/hide', {
    space: space.value,
    person_id: person.id,
  })
  if (res === null) return
  toast(`已隐藏 #${person.id}`, 'ok')
  advance()
}

function pick(i: number): void {
  selected.value = i
  void submit()
}

onBeforeUnmount(() => {
  if (debounceTimer !== null) window.clearTimeout(debounceTimer)
})

void loadStatus()
</script>

<template>
  <section class="card qm">
    <header class="qm-head">
      <div>
        <h3>未命名人物速并</h3>
        <p class="muted">
          快速整理群晖照片中尚未命名的人物：输入新名字即可命名，从联想列表中选择即可并入已有的人物，或直接隐藏非人物误检。
        </p>
      </div>
      <div class="qm-head-actions">
        <label v-if="(status?.spaces.length ?? 0) > 1" class="qm-space">
          空间
          <select class="select" v-model="space" :disabled="loading" @change="loaded = false">
            <option v-for="s in status?.spaces" :key="s" :value="s">{{ SPACE_LABELS[s] ?? s }}</option>
          </select>
        </label>
        <button type="button" class="btn" :disabled="loading" @click="load(loaded)">
          {{ loading ? '加载中…' : loaded ? '重新加载' : '加载未命名人物' }}
        </button>
      </div>
    </header>

    <p v-if="status && !status.nas_configured" class="muted">
      尚未配置群晖 NAS 凭据，请先前往「系统设置」完成配置。
    </p>

    <p v-else-if="!loaded && !loading" class="muted">
      尚未加载列表，点击「加载未命名人物」即可开始。未命名人物速并直接从群晖获取人脸列表，不依赖同步任务，随时均可使用。
    </p>

    <p v-else-if="loading" class="muted">正在从群晖 NAS 获取人物列表…</p>

    <p v-else-if="!people.length" class="muted">当前空间没有未命名人物，无需处理 :D</p>

    <p v-else-if="done" class="muted">
      处理完成 — 共处理或跳过 {{ people.length }} 位人物。
      <button type="button" class="btn btn-sm" @click="load(true)">重新加载列表</button>
    </p>

    <template v-else-if="current">
      <div class="qm-thumbs">
        <figure class="qm-fig">
          <img v-if="current.thumb_url" class="qm-thumb" :src="current.thumb_url" alt="" />
          <div v-else class="qm-thumb qm-thumb-empty">无缩略图</div>
          <figcaption class="muted">
            #{{ current.id }}
            <template v-if="current.item_count != null"> · {{ current.item_count }} 张照片</template>
          </figcaption>
        </figure>
        <div class="qm-arrow" aria-hidden="true">→</div>
        <figure class="qm-fig">
          <img v-if="target?.thumb_url" class="qm-thumb" :src="target.thumb_url" alt="" />
          <div v-else class="qm-thumb qm-thumb-empty">输入姓名以预览合并目标</div>
          <figcaption class="muted">{{ target ? target.name : '—' }}</figcaption>
        </figure>
      </div>

      <p class="qm-progress">
        第 {{ index + 1 }} / {{ people.length }} 位人物
        <a v-if="current.link" :href="current.link" target="_blank" rel="noreferrer noopener"
          >在群晖照片中查看</a
        >
      </p>

      <input
        ref="inputEl"
        class="input qm-input"
        type="text"
        autocomplete="off"
        :disabled="busy"
        placeholder="输入新姓名命名，或搜索并入已有的人物（输入 11 直接隐藏）"
        v-model="query"
        @input="onInput"
        @keydown="onKeydown"
      />

      <ul v-if="searching || suggestions.length" class="qm-suggestions">
        <li v-if="searching" class="muted">搜索中…</li>
        <li
          v-for="(s, i) in suggestions"
          :key="s.id"
          :class="{ selected: i === selected }"
          @click="pick(i)"
        >
          {{ s.name }} <span class="muted">(#{{ s.id }})</span>
        </li>
      </ul>

      <div class="qm-actions">
        <button type="button" class="btn" :disabled="index === 0 || busy" @click="back">
          上一位
        </button>
        <button type="button" class="btn" :disabled="busy" @click="advance()">跳过</button>
        <button type="button" class="btn" :disabled="busy" @click="advance(10)">跳过 10 位</button>
        <button type="button" class="btn" :disabled="busy" @click="advance(100)">跳过 100 位</button>
        <button type="button" class="btn btn-danger" :disabled="busy" @click="hide">隐藏</button>
      </div>

      <p class="muted">
        回车键提交 · ↑/↓ 选择合并目标 · 空回车跳过 · 输入 11 立即隐藏。
      </p>
    </template>
  </section>
</template>

<style scoped>
.qm {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.qm h3 {
  margin: 0;
}
.qm-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--sp-3);
  flex-wrap: wrap;
}
.qm-head p {
  margin: var(--sp-1) 0 0;
  max-width: 100ch;
}
.qm-head-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.qm-space {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: var(--fs-sm);
}
.qm-thumbs {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}
.qm-fig {
  margin: 0;
  flex: 0 0 auto;
  text-align: center;
}
.qm-thumb {
  width: 180px;
  height: 180px;
  object-fit: cover;
  border-radius: var(--radius);
  background: var(--bg-sunken);
}
.qm-thumb-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--fs-sm);
  color: var(--text-2);
  padding: 5px;
  border: 1px dashed var(--border-soft);
}
.qm-arrow {
  font-size: 1.5rem;
  color: var(--text-2);
}
.qm-progress {
  display: flex;
  gap: var(--sp-2);
  align-items: baseline;
  margin: 0;
}
.qm-input {
  width: 100%;
}
.qm-suggestions {
  list-style: none;
  margin: 0;
  padding: 0;
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
  max-height: 180px;
  overflow-y: auto;
}
.qm-suggestions li {
  padding: var(--sp-1) var(--sp-2);
  cursor: pointer;
}
.qm-suggestions li.selected,
.qm-suggestions li:hover {
  background: var(--sel-tint);
}
.qm-actions {
  display: flex;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
</style>
