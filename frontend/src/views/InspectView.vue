<script setup lang="ts">
// Inspect: one photo, everything we know about it. The photo comes from the NAS
// thumbnail proxy and every box is drawn on top of it as a percentage of the
// rendered frame, so ours (pixel coords, normalized server-side) and Synology's
// (already 0..1) land in the same coordinate space.
//
// The photo id lives in the path (/inspect/:space/:id) so a report is linkable:
// the review cards point here instead of straight at Synology Photos, and the
// NAS link moves inside the report.
import { ref, computed, watch, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getJSON, postJSON, ApiError } from '../api/client'
import { usePanZoom } from '../composables/usePanZoom'
import { toast } from '../stores/toasts'
import PersonPickerDialog from '../components/review/PersonPickerDialog.vue'
import type {
  InspectAssignResponse,
  InspectFace,
  InspectMeta,
  InspectPoint,
  InspectReport,
  NormBox,
  ReviewPersonSuggestion,
} from '../api/types'

const route = useRoute()
const router = useRouter()

const stage = ref<HTMLElement | null>(null)
const pan = usePanZoom(stage)

const meta = ref<InspectMeta | null>(null)
const report = ref<InspectReport | null>(null)
const loading = ref(false)
const error = ref('')

const query = ref('')
const space = ref('personal')

const showOurs = ref(true)
const showTheirs = ref(true)
const showLandmarks = ref(false)
const selected = ref<number | null>(null)

/** Set when the served image is not shaped like the frame the boxes assume. */
const skewed = ref(false)
/** Set when that mismatch is a transpose — a swapped pair, not a random one. */
const transposed = ref(false)
/**
 * Set when we re-normalized our boxes against the transposed frame.
 *
 * Two different faults look alike from the server: the frame guess is the
 * transpose of the truth (same pixels, wrong divisors — boxes squash along one
 * axis and slide toward a corner), or the photo is genuinely a quarter-turn
 * out. `resolve_frame` tells them apart with Synology's boxes, but only when
 * the photo has some. When it does not, the browser holds the one measurement
 * nobody else has: the shape of the photo that actually arrived. A frame whose
 * aspect is the transpose of that is the wrong divisor, near enough always —
 * both frames describe the same upright photo, so they cannot legitimately
 * disagree about which side is longer unless the content really is turned, and
 * a real turn is what the server would have found evidence for.
 */
const reframed = ref(false)

/**
 * Quarter-turn clockwise applied to our boxes so they land on the served photo,
 * as `resolve_frame` measured it against Synology's boxes.
 *
 * There is deliberately no manual override. A turn is the rarer of the two ways
 * an overlay goes wrong by a wide margin — over a real library the frame needed
 * swapping on 0.61% of photos and turning on 0.008%, and that one photo had
 * Synology faces, so the server settled it unaided. A control for that would be
 * one a reader reaches for on the far more common frame fault, where it is the
 * wrong tool and makes the picture worse.
 *
 * The photo itself is never rotated: turning it would leave the reader
 * squinting at a sideways picture to check a box, and the stage's aspect is the
 * thumbnail's, so the overlay would have to be re-based on a frame the layout
 * does not have.
 */
const rotation = computed(() => report.value?.display.rotation ?? 0)

const spaces = computed(() => meta.value?.spaces ?? ['personal'])

const SPACE_LABELS: Record<string, string> = {
  personal: '个人空间',
  shared: '共享空间',
}
const KIND_LABELS: Record<string, string> = {
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

function fmtTime(t: number | null | undefined): string {
  return t ? new Date(t * 1000).toLocaleString() : '—'
}

function fmtScore(n: number | null | undefined, digits = 3): string {
  return n == null ? '—' : n.toFixed(digits)
}

function fmtBytes(n: number | null | undefined): string {
  if (n == null) return '—'
  const u = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024
    i++
  }
  return (i === 0 ? v : v.toFixed(1)) + ' ' + u[i]
}

/**
 * Read a photo id out of whatever the user pasted: a bare id, `space/id`, a
 * Synology deep link (…/timeline/item/42069) or an Inspect link of our own.
 */
function parseTarget(raw: string): { space: string; id: number } | null {
  const text = raw.trim()
  if (!text) return null
  const deep = /(?:^|\/)(personal|shared)(?:_space)?\/(?:timeline\/item\/)?(\d+)/.exec(text)
  if (deep) return { space: deep[1], id: Number(deep[2]) }
  const item = /timeline\/item\/(\d+)/.exec(text)
  if (item) return { space: space.value, id: Number(item[1]) }
  const bare = /^\d+$/.exec(text)
  if (bare) return { space: space.value, id: Number(bare[0]) }
  return null
}

function submit(): void {
  const target = parseTarget(query.value)
  if (!target) {
    error.value = '请输入照片 ID，或粘贴照片链接。'
    return
  }
  error.value = ''
  void router.push(`/inspect/${target.space}/${target.id}`)
}

async function load(sp: string, id: number): Promise<void> {
  loading.value = true
  error.value = ''
  selected.value = null
  skewed.value = false
  transposed.value = false
  reframed.value = false
  pan.reset()
  try {
    report.value = await getJSON<InspectReport>(`/api/inspect/${sp}/${id}`)
    space.value = sp
  } catch (e: unknown) {
    report.value = null
    error.value =
      e instanceof ApiError ? e.message : (e as Error).message || '无法加载该照片'
  } finally {
    loading.value = false
  }
}

function syncFromRoute(): void {
  const sp = route.params.space as string | undefined
  const id = route.params.photoId as string | undefined
  if (!sp || !id) {
    report.value = null
    return
  }
  query.value = String(id)
  void load(sp, Number(id))
}

/**
 * Measures the photo that actually arrived against the frame the boxes assume,
 * and re-frames when the two are transposed and the server had nothing to check
 * its guess against. A mismatch that is neither — a crop, a stretch — is left
 * alone and reported, because no re-normalizing or turning fixes that.
 */
function onImageLoad(event: Event): void {
  const img = event.target as HTMLImageElement
  const display = report.value?.display
  if (!display?.width || !display?.height || !img.naturalWidth || !img.naturalHeight) return
  const shown = img.naturalWidth / img.naturalHeight
  const expected = display.width / display.height
  skewed.value = Math.abs(shown - expected) > 0.05 * expected
  transposed.value = skewed.value && Math.abs(shown - 1 / expected) <= 0.05 / expected
  // Never overrule a frame Synology's own boxes chose — that is real evidence,
  // and a legitimately transposed one means the content is turned, which the
  // same vote would have found.
  reframed.value =
    transposed.value && display.rotation === 0 && display.rotation_source === 'none'
}

/**
 * Renormalize a fraction of the server's frame into a fraction of its
 * transpose. The pixels never moved; only the numbers they were divided by did,
 * so undoing it is a rescale by the ratio of the frames' sides.
 */
function reframe(box: NormBox): NormBox {
  const d = report.value?.display
  if (!reframed.value || !d?.width || !d?.height) return box
  const kx = d.width / d.height
  const ky = d.height / d.width
  return { x: box.x * kx, y: box.y * ky, w: box.w * kx, h: box.h * ky }
}

/**
 * One of our 0..1 boxes as it should sit on the served photo: re-framed if the
 * divisors were swapped, then turned if the content is. Width and height swap
 * on a quarter-turn because the frame they are a fraction of does too, which is
 * what keeps the box the same shape in pixels.
 */
function turned(box: NormBox): NormBox {
  const { x, y, w, h } = reframe(box)
  if (rotation.value === 90) return { x: 1 - y - h, y: x, w: h, h: w }
  if (rotation.value === 180) return { x: 1 - x - w, y: 1 - y - h, w, h }
  if (rotation.value === 270) return { x: y, y: 1 - x - w, w: h, h: w }
  return { x, y, w, h }
}

function turnedPoint(p: InspectPoint): InspectPoint {
  const d = report.value?.display
  let { x, y } = p
  if (reframed.value && d?.width && d?.height) {
    x = x * (d.width / d.height)
    y = y * (d.height / d.width)
  }
  if (rotation.value === 90) return { x: 1 - y, y: x }
  if (rotation.value === 180) return { x: 1 - x, y: 1 - y }
  if (rotation.value === 270) return { x: y, y: 1 - x }
  return { x, y }
}

/** The frame our boxes are actually drawn against, after any re-framing. */
const activeFrame = computed(() => {
  const d = report.value?.display
  if (!d?.width || !d?.height) return null
  return reframed.value ? { w: d.height, h: d.width } : { w: d.width, h: d.height }
})

/**
 * What the page had to do to line the boxes up, or could not. The warning this
 * replaced ended at "may be misaligned": a doubt, with nothing said about which
 * of the two faults it was or whether anything had been done about it.
 */
const alignment = computed<{ tone: 'info' | 'warn'; text: string } | null>(() => {
  const r = report.value
  if (!r) return null
  const stored = `${r.photo.width ?? '?'}×${r.photo.height ?? '?'}，方向值 ${
    r.photo.orientation ?? '—'
  }`
  const parts: string[] = []
  let tone: 'info' | 'warn' = 'info'

  if (reframed.value) {
    parts.push(
      `记录的分辨率（${stored}）与群晖 NAS 返回的照片宽高互换，因此本页已按实际返回画幅重新换算检测框位置。`,
    )
  } else if (skewed.value && transposed.value && rotation.value === 0) {
    tone = 'warn'
    parts.push(
      `群晖 NAS 返回的照片与检测框所依据的画幅（${stored}）宽高互换，且群晖照片中该图无人脸框可供校准，检测框可能偏移。`,
    )
  } else if (skewed.value && rotation.value === 0) {
    tone = 'warn'
    parts.push(
      `群晖 NAS 返回的照片比例与记录的分辨率（${stored}）不一致，且并非旋转导致，检测框可能偏移。`,
    )
  }

  if (rotation.value !== 0) {
    parts.push(
      `已参照群晖照片自带人脸框将检测框旋转 ${rotation.value}° 以对齐照片。`,
    )
  }
  return parts.length ? { tone, text: parts.join(' ') } : null
})

function pct(v: number): string {
  return (v * 100).toFixed(3) + '%'
}

/**
 * Place a 0..1 box in the unscaled overlay: percentages of the viewport times
 * the zoom, shifted by the pan. The overlay is never transformed, so borders
 * and labels stay crisp and their own size however far the reader zooms in.
 */
function boxStyle(box: { x: number; y: number; w: number; h: number }) {
  const k = pan.scale.value
  return {
    left: `calc(${pct(box.x * k)} + ${pan.x.value}px)`,
    top: `calc(${pct(box.y * k)} + ${pan.y.value}px)`,
    width: pct(box.w * k),
    height: pct(box.h * k),
  }
}

function pointStyle(p: { x: number; y: number }) {
  const k = pan.scale.value
  return {
    left: `calc(${pct(p.x * k)} + ${pan.x.value}px)`,
    top: `calc(${pct(p.y * k)} + ${pan.y.value}px)`,
  }
}

// -- tagging a face nothing proposed ---------------------------------------- #
// Inspect's only write, and it writes the review queue rather than the NAS: the
// row lands approved and Apply still holds the flags that reach Synology. Which
// flag depends on whether Synology already named this face — the server decides
// that, and `face.syno` is why the button can say so up front.
const picker = ref<InspectFace | null>(null)
const assigning = ref(false)

function isTagged(face: InspectFace): boolean {
  return face.syno?.person_id != null
}

/** Re-read the report after a tag: same photo, same view, new Review rows. */
async function refresh(): Promise<void> {
  const r = report.value
  if (!r) return
  try {
    report.value = await getJSON<InspectReport>(`/api/inspect/${r.space}/${r.photo_id}`)
  } catch {
    // The write already succeeded and said so; a stale report is the lesser evil.
  }
}

async function onAssign(target: ReviewPersonSuggestion): Promise<void> {
  const face = picker.value
  if (!face || assigning.value) return
  assigning.value = true
  try {
    const res = await postJSON<InspectAssignResponse>(
      `/api/inspect/face/${face.face_id}/assign`,
      {
        space: report.value?.space,
        person_id: target.person_id,
        person_name: target.name,
      },
    )
    picker.value = null
    toast(
      res.kind === 'reassign'
        ? `已加入待写回队列：将人脸 #${face.face_id} 改判为 ${target.name}。需在「写回群晖」中勾选「改判人物」才会生效。`
        : `已加入待写回队列：将人脸 #${face.face_id} 标记为 ${target.name}。请前往「写回群晖」执行写入。`,
      'ok',
    )
    await refresh()
  } catch (e) {
    toast(
      e instanceof ApiError ? e.message : (e as Error).message || '加入待写回队列失败',
      'error',
    )
  } finally {
    assigning.value = false
  }
}

function faceLabel(face: InspectFace): string {
  const score = face.det_score == null ? '' : ' ' + face.det_score.toFixed(2)
  return `#${face.face_id} ${face.detector}${score}`
}

const reviewFor = computed(() => {
  const map = new Map<number, string[]>()
  for (const item of report.value?.review_items ?? []) {
    for (const fid of item.face_ids) {
      const list = map.get(fid) ?? []
      const kindLabel = KIND_LABELS[item.kind] ?? item.kind
      const statusLabel = STATUS_LABELS[item.status] ?? item.status
      list.push(`${kindLabel} · ${statusLabel}`)
      map.set(fid, list)
    }
  }
  return map
})

/** Review rows about the photo that name no face of ours (merges, orphans). */
const otherReviewItems = computed(() =>
  (report.value?.review_items ?? []).filter((it) => it.face_ids.length === 0),
)

function select(faceId: number): void {
  selected.value = selected.value === faceId ? null : faceId
  if (selected.value === null) return
  const box = report.value?.faces.find((f) => f.face_id === faceId)?.box
  if (box) {
    const b = turned(box)
    pan.focus(b.x + b.w / 2, b.y + b.h / 2)
  }
  document.getElementById(`face-${faceId}`)?.scrollIntoView({ block: 'nearest' })
}

/** A box click that ended a pan is a pan, not a selection. */
function clickBox(faceId: number): void {
  if (!pan.dragged.value) select(faceId)
}

onMounted(async () => {
  try {
    meta.value = await getJSON<InspectMeta>('/api/inspect/meta')
    space.value = meta.value.spaces[0] ?? 'personal'
  } catch {
    // Non-fatal: the space picker just falls back to `personal`.
  }
  syncFromRoute()
})

watch(() => [route.params.space, route.params.photoId], syncFromRoute)
</script>

<template>
  <div class="page inspect-page">
    <section class="card ins-finder">
      <h3>照片检视</h3>
      <p class="muted">
        查看单张照片中检出的所有人脸及其置信度评分，并与群晖照片中已有的人脸标注进行对照。
      </p>
      <form class="ins-form" @submit.prevent="submit">
        <select
          v-if="spaces.length > 1"
          class="select input-sm"
          v-model="space"
          aria-label="空间"
        >
          <option v-for="s in spaces" :key="s" :value="s">{{ SPACE_LABELS[s] ?? s }}</option>
        </select>
        <input
          class="input"
          v-model="query"
          placeholder="输入群晖照片 ID，或粘贴照片链接"
          aria-label="照片 ID"
        />
        <button type="submit" class="btn btn-primary">检视</button>
      </form>
      <p v-if="error" class="ins-error">{{ error }}</p>
    </section>

    <p v-if="loading" class="muted">加载中…</p>

    <template v-if="report && !loading">
      <section class="card ins-canvas-card">
        <header class="ins-head">
          <div>
            <h3>{{ report.photo.filename || `照片 #${report.photo_id}` }}</h3>
            <p class="muted">
              {{ SPACE_LABELS[report.space] ?? report.space }} · ID {{ report.photo_id }} · {{ fmtTime(report.photo.time) }}
              <span v-if="report.photo.deleted"> · 已在群晖 NAS 上删除</span>
            </p>
          </div>
          <a
            v-if="report.nas_url"
            class="btn"
            :href="report.nas_url"
            target="_blank"
            rel="noopener"
            >在群晖照片中查看</a
          >
        </header>

        <div class="ins-toggles">
          <label class="opt-check"
            ><input type="checkbox" v-model="showOurs" /> Synopticon 检出人脸 ({{ report.faces.length }})
          </label>
          <label class="opt-check"
            ><input type="checkbox" v-model="showTheirs" /> 群晖原有人脸 ({{
              report.syno_faces.length
            }})
          </label>
          <label class="opt-check"><input type="checkbox" v-model="showLandmarks" /> 关键点</label>
        </div>

        <div
          class="ins-stage"
          ref="stage"
          :class="{ zoomed: pan.zoomed.value, dragging: pan.dragging.value }"
          @wheel="pan.onWheel"
          @pointerdown="pan.onPointerDown"
          @dblclick="pan.onDoubleClick"
        >
          <div class="ins-layer" :style="{ transform: pan.transform.value }">
            <img
              class="ins-img"
              :src="report.image_url"
              :alt="report.photo.filename || '照片'"
              draggable="false"
              @load="onImageLoad"
            />
          </div>

          <div class="ins-overlay">
            <template v-if="showOurs">
              <button
                v-for="face in report.faces"
                :key="face.face_id"
                v-show="face.box"
                type="button"
                class="ins-box ours"
                :class="{ sel: selected === face.face_id }"
                :style="boxStyle(turned(face.box ?? { x: 0, y: 0, w: 0, h: 0 }))"
                :title="faceLabel(face)"
                @click="clickBox(face.face_id)"
              >
                <span class="ins-tag">{{ faceLabel(face) }}</span>
              </button>
            </template>
            <template v-if="showLandmarks">
              <template v-for="face in report.faces" :key="'lm-' + face.face_id">
                <span
                  v-for="(p, i) in face.landmarks || []"
                  :key="i"
                  class="ins-point"
                  :style="pointStyle(turnedPoint(p))"
                ></span>
              </template>
            </template>
            <template v-if="showTheirs">
              <span
                v-for="sf in report.syno_faces"
                :key="'syno-' + sf.syno_face_id"
                class="ins-box theirs"
                :style="boxStyle(sf.box)"
              >
                <span class="ins-tag">{{ sf.name || '未命名' }}</span>
              </span>
            </template>
          </div>

          <div class="ins-zoom" role="group" aria-label="缩放控制" @pointerdown.stop @dblclick.stop>
            <span v-if="pan.zoomed.value" class="ins-zoom-level"
              >{{ Math.round(pan.scale.value * 100) }}%</span
            >
            <button
              type="button"
              class="ins-zoom-btn"
              :disabled="pan.atMax.value"
              title="放大 — 可使用滚轮、双指捏合或双击照片"
              aria-label="放大"
              @click="pan.zoomIn"
            >
              +
            </button>
            <button
              type="button"
              class="ins-zoom-btn"
              :disabled="!pan.zoomed.value"
              title="缩小"
              aria-label="缩小"
              @click="pan.zoomOut"
            >
              &minus;
            </button>
            <button
              type="button"
              class="ins-zoom-btn"
              :disabled="!pan.zoomed.value"
              title="自适应完整照片"
              aria-label="自适应完整照片"
              @click="pan.reset"
            >
              &#9633;
            </button>
          </div>
        </div>

        <p v-if="alignment" class="ins-align" :class="alignment.tone">
          {{ alignment.text }}
        </p>
      </section>

      <section class="card">
        <h3>检出的人脸</h3>
        <p v-if="!report.faces.length" class="muted">
          尚未检出人脸<template v-if="!report.extract"> — 此照片尚未运行「人脸检测与提取」</template
          >。
        </p>
        <div class="ins-faces">
          <article
            v-for="face in report.faces"
            :key="face.face_id"
            class="ins-face"
            :id="`face-${face.face_id}`"
            :class="{ sel: selected === face.face_id }"
            @click="select(face.face_id)"
          >
            <div class="ins-face-crop">
              <img
                v-if="face.crop_url"
                class="ins-crop"
                :src="face.crop_url"
                alt=""
                loading="lazy"
              />
              <div v-else class="ins-crop ins-crop-missing" title="磁盘上无裁切图">无裁切图</div>
              <button
                type="button"
                class="btn btn-sm ins-tag-btn"
                :title="
                  isTagged(face)
                    ? '将此人脸加入队列，改判为其他人物'
                    : '手动将此人脸标记为指定人物（即使系统未生成识别建议）'
                "
                @click.stop="picker = face"
              >
                {{ isTagged(face) ? '改判人物' : '标记为人物' }}
              </button>
            </div>
            <dl class="ins-facts">
              <dt>人脸 ID</dt>
              <dd class="mono">#{{ face.face_id }}</dd>
              <dt>检测器</dt>
              <dd>{{ face.detector }}</dd>
              <dt>检测分</dt>
              <dd class="mono">
                {{ fmtScore(face.det_score) }}
                <span v-if="face.det_score_secondary != null" class="muted"
                  >· 次检 {{ fmtScore(face.det_score_secondary) }}</span
                >
              </dd>
              <dt>画质分</dt>
              <dd class="mono">{{ fmtScore(face.quality, 1) }}</dd>
              <dt>检测框</dt>
              <dd class="mono">
                {{ Math.round(face.bbox.x) }},{{ Math.round(face.bbox.y) }} ·
                {{ Math.round(face.bbox.w) }}×{{ Math.round(face.bbox.h) }}
              </dd>
              <dt>人脸分组</dt>
              <dd>
                <template v-if="face.cluster">
                  #{{ face.cluster.cluster_id }}（{{ face.cluster.size ?? '?' }} 张人脸，批次
                  {{ face.cluster.run_id }}）
                  <template v-if="face.cluster.mapped_person_id != null">
                    →
                    <a
                      v-if="face.cluster.mapped_person_url"
                      :href="face.cluster.mapped_person_url"
                      target="_blank"
                      rel="noopener"
                      >{{ face.cluster.mapped_person_name || face.cluster.mapped_person_id }}</a
                    >
                    <template v-else>{{
                      face.cluster.mapped_person_name || face.cluster.mapped_person_id
                    }}</template>
                    <span v-if="face.cluster.vote_fraction != null" class="muted">
                      · {{ (face.cluster.vote_fraction * 100).toFixed(0) }}% 投票一致</span
                    >
                  </template>
                </template>
                <span v-else class="muted">未分组</span>
              </dd>
              <dt>特征向量</dt>
              <dd>
                <span v-if="!face.embeddings.length" class="muted">无</span>
                <span v-else>{{
                  face.embeddings.map((e) => `${e.model} (${e.variant})`).join(', ')
                }}</span>
              </dd>
              <dt v-if="face.restored">画质修复</dt>
              <dd v-if="face.restored" class="mono">
                差异度 {{ fmtScore(face.restore_disagreement) }}
              </dd>
              <dt>群晖标注</dt>
              <dd>
                <template v-if="face.syno">
                  <template v-if="face.syno.person_id != null">{{
                    face.syno.name || `#${face.syno.person_id}`
                  }}</template>
                  <span v-else class="muted">有框，未命名</span>
                  <span class="muted"> · IoU {{ face.syno.iou.toFixed(2) }}</span>
                </template>
                <span v-else class="muted">此处无群晖人脸框</span>
              </dd>
              <dt>审核记录</dt>
              <dd>
                <span v-if="!reviewFor.get(face.face_id)" class="muted">无</span>
                <span v-else>{{ reviewFor.get(face.face_id)?.join('，') }}</span>
              </dd>
              <dt>处理版本</dt>
              <dd class="mono">
                {{ face.pipeline_version }}
                <span
                  v-if="meta?.pipeline_version && meta.pipeline_version !== face.pipeline_version"
                  class="muted"
                  >· 已过时</span
                >
              </dd>
            </dl>
          </article>
        </div>
      </section>

      <section v-if="report.syno_faces.length" class="card">
        <h3>群晖原有人脸</h3>
        <table class="ins-table">
          <thead>
            <tr>
              <th>人脸 ID</th>
              <th>人物</th>
              <th>人脸框 (0–1)</th>
              <th>同步时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="sf in report.syno_faces" :key="sf.syno_face_id">
              <td class="mono">{{ sf.syno_face_id }}</td>
              <td>
                <a
                  v-if="sf.person_url"
                  :href="sf.person_url"
                  target="_blank"
                  rel="noopener"
                  >{{ sf.name || sf.person_id }}</a
                >
                <span v-else class="muted">{{ sf.name || '未命名' }}</span>
              </td>
              <td class="mono">
                {{ sf.box.x.toFixed(3) }}, {{ sf.box.y.toFixed(3) }} ·
                {{ sf.box.w.toFixed(3) }}×{{ sf.box.h.toFixed(3) }}
              </td>
              <td>{{ fmtTime(sf.synced_at) }}</td>
            </tr>
          </tbody>
        </table>
      </section>

      <section v-if="otherReviewItems.length" class="card">
        <h3>其他审核条目</h3>
        <p class="muted">涉及此照片、但未关联当前任意人脸的队列条目。</p>
        <ul class="ins-list">
          <li v-for="it in otherReviewItems" :key="it.item_id">
            <span class="mono">#{{ it.item_id }}</span> {{ KIND_LABELS[it.kind] ?? it.kind }} · {{ STATUS_LABELS[it.status] ?? it.status }}
            <span v-if="it.confidence != null" class="muted"
              >· {{ fmtScore(it.confidence, 2) }}</span
            >
          </li>
        </ul>
      </section>

      <section class="card ins-meta">
        <h3>照片信息</h3>
        <dl class="ins-facts">
          <dt>分辨率</dt>
          <dd class="mono">
            {{ report.photo.width ?? '?' }}×{{ report.photo.height ?? '?' }}
            <span class="muted"
              >· 实际画幅 {{ activeFrame?.w ?? '?' }}×{{ activeFrame?.h ?? '?' }}
              <template v-if="reframed">（已换算）</template> · 方向值
              {{ report.photo.orientation ?? '—' }}<template v-if="rotation !== 0">
                · 检测框已旋转 {{ rotation }}°</template
              ></span
            >
          </dd>
          <dt>文件大小</dt>
          <dd class="mono">{{ fmtBytes(report.photo.filesize) }}</dd>
          <dt>类型</dt>
          <dd>{{ report.photo.type || '—' }}</dd>
          <dt>缓存键</dt>
          <dd class="mono">{{ report.photo.cache_key || '—' }}</dd>
          <dt>哈希值</dt>
          <dd class="mono">
            sha256 {{ report.photo.sha256?.slice(0, 12) || '—' }} · pHash
            {{ report.photo.phash || '—' }}
          </dd>
          <dt v-if="report.photo.similar_top_pick">相似组</dt>
          <dd v-if="report.photo.similar_top_pick" class="mono">
            首选 {{ report.photo.similar_top_pick }}
          </dd>
          <dt>同步时间</dt>
          <dd>{{ fmtTime(report.photo.synced_at) }}</dd>
          <dt>检测记录</dt>
          <dd>
            <template v-if="report.extract">
              {{ fmtTime(report.extract.processed_at) }} ·
              {{ report.extract.face_count }} 张人脸 ·
              <span class="mono">{{ report.extract.pipeline_version }}</span>
              <span v-if="report.extract.stale" class="muted"> · 照片此后发生变更</span>
            </template>
            <span v-else class="muted">尚未运行</span>
          </dd>
          <dt>检测阈值</dt>
          <dd class="mono">
            SCRFD {{ report.detection.scrfd_score }} · YOLO {{ report.detection.yolo_score }} · NMS
            {{ report.detection.nms_iou }} · 交叉验证 {{ report.detection.cross_iou }} · 最小人脸
            {{ report.detection.min_face_px }}px
          </dd>
        </dl>
      </section>
    </template>

    <PersonPickerDialog
      v-if="picker"
      :mode="isTagged(picker) ? 'reassign' : 'assign'"
      :source-label="`人脸 #${picker.face_id}`"
      :source-crops="[picker.crop_url]"
      :space="report?.space"
      :source-key="picker.face_id"
      :note="
        isTagged(picker)
          ? `群晖照片当前将此人脸标记为 ${picker.syno?.name || '#' + picker.syno?.person_id}。` +
            '确认后将加入待写回队列——需在「写回群晖」中勾选「改判人物」才会写入群晖。'
          : undefined
      "
      :busy="assigning"
      @confirm="onAssign"
      @cancel="picker = null"
    />
  </div>
</template>

<style scoped>
.ins-finder h3,
.ins-head h3 {
  margin: 0 0 var(--sp-1);
}
.inspect-page > .card {
  margin-bottom: var(--sp-4);
}
.ins-form {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
  flex-wrap: wrap;
}
.ins-form .input {
  flex: 1;
  min-width: 220px;
}
.ins-error {
  color: var(--danger);
  margin: var(--sp-2) 0 0;
}
.ins-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-3);
}
.ins-head p {
  margin: 0;
}
.ins-toggles {
  display: flex;
  gap: var(--sp-4);
  flex-wrap: wrap;
  margin: var(--sp-3) 0;
}
.ins-stage {
  position: relative;
  display: block;
  line-height: 0;
  background: var(--bg-sunken);
  border-radius: var(--radius);
  overflow: hidden;
  /* Vertical swipes stay page scrolls until the reader zooms in. */
  touch-action: pan-y;
}
.ins-stage.zoomed {
  touch-action: none;
  cursor: grab;
}
.ins-stage.dragging {
  cursor: grabbing;
}
.ins-layer {
  position: relative;
  transform-origin: 0 0;
  user-select: none;
}
/* The photo alone is transformed; the boxes are placed over it in viewport
   coordinates, so nothing over the photo is a scaled-up bitmap. */
.ins-overlay {
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.ins-img {
  display: block;
  width: 100%;
  height: auto;
}
.ins-box {
  position: absolute;
  padding: 0;
  background: transparent;
  border: 2px solid var(--action);
  border-radius: 2px;
  cursor: pointer;
  pointer-events: auto;
}
.ins-box.theirs {
  border-color: var(--warn);
  border-style: dashed;
  cursor: default;
  pointer-events: none;
}
.ins-box.sel {
  border-color: var(--ok);
  box-shadow: 0 0 0 2px rgba(31, 157, 77, 0.35);
}
.ins-tag {
  position: absolute;
  left: 0;
  bottom: 100%;
  font-size: var(--fs-sm);
  line-height: 1.4;
  white-space: nowrap;
  padding: 0 4px;
  color: #fff;
  background: var(--action);
  border-radius: 2px 2px 0 0;
}
.ins-box.theirs .ins-tag {
  background: var(--warn);
}
.ins-box.sel .ins-tag {
  background: var(--ok);
}
.ins-point {
  position: absolute;
  width: 5px;
  height: 5px;
  margin: -3px 0 0 -3px;
  border-radius: 50%;
  background: var(--ok);
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.8);
}
.ins-zoom {
  position: absolute;
  right: var(--sp-3);
  bottom: var(--sp-3);
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: var(--sp-1);
  line-height: 1;
  z-index: 2;
}
.ins-zoom-level {
  font-size: var(--fs-sm);
  text-align: center;
  padding: 3px 4px;
  color: var(--text-2);
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-menu);
}
.ins-zoom-btn {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--fs-lg);
  cursor: pointer;
  color: var(--text);
  background: var(--bg-raised);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-menu);
}
.ins-zoom-btn:hover:not(:disabled) {
  background: var(--bg-sunken);
}
.ins-zoom-btn:disabled {
  color: var(--text-3);
  cursor: default;
}
.ins-align {
  margin: var(--sp-3) 0 0;
  font-size: var(--fs-sm);
}
.ins-align.warn {
  color: var(--warn);
}
.ins-align.info {
  color: var(--text-2);
}
.ins-faces {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: var(--sp-3);
  margin-top: var(--sp-3);
}
.ins-face {
  display: flex;
  gap: var(--sp-3);
  padding: var(--sp-3);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
  cursor: pointer;
}
.ins-face.sel {
  border-color: var(--ok);
  background: var(--sel-tint);
}
.ins-face-crop {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  flex: none;
  width: 96px;
}
.ins-tag-btn {
  width: 100%;
  background: var(--action);
}
.ins-crop {
  width: 96px;
  height: 96px;
  object-fit: cover;
  border-radius: var(--radius);
  flex: none;
}
.ins-crop-missing {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: var(--fs-sm);
  color: var(--text-3);
  background: var(--bg-sunken);
}
.ins-facts {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px var(--sp-3);
  margin: 0;
  font-size: var(--fs-sm);
  min-width: 0;
}
.ins-facts dt {
  color: var(--text-2);
}
.ins-facts dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.ins-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: var(--sp-3);
  font-size: var(--fs-sm);
}
.ins-table th,
.ins-table td {
  text-align: left;
  padding: var(--sp-1) var(--sp-2);
  border-bottom: 1px solid var(--border-soft);
}
.ins-list {
  margin: var(--sp-2) 0 0;
  padding-left: var(--sp-4);
}
</style>
