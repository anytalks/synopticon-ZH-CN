<script setup lang="ts">
// Utilities: interactive tools that act on the library itself rather than on
// local pipeline state (which is what Maintenance is for). QuickMerger talks to
// the NAS directly through /api/quickmerger/*; deduplication runs as a job, so
// it shares the standard JobPanel and the typed-phrase consent gate the server
// re-checks in validate_consent. The two backups are plain downloads rather
// than jobs — what they produce is a file the browser has to receive, not a log.
import { ref, reactive, onMounted } from 'vue'
import JobPanel from '../components/JobPanel.vue'
import QuickMerger from '../components/QuickMerger.vue'
import { ApiError, getJSON, downloadFile } from '../api/client'
import { toast } from '../stores/toasts'
import { confirm } from '../composables/useConfirm'

const PHRASE_DEDUPE = 'delete duplicates'

const panel = ref<InstanceType<typeof JobPanel> | null>(null)
const dedupe = reactive({ exact: true, visual: false, threshold: '' })

interface BackupInfo {
  config: { path: string; exists: boolean; secret_keys: string[] }
  database: { backend: string; bytes: number | null }
}
const backup = ref<BackupInfo | null>(null)
const includeSecrets = ref(false)
const busyConfig = ref(false)
const busyDatabase = ref(false)

function fmtBytes(n: number | null | undefined): string {
  if (n == null) return '未知大小'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024
    i++
  }
  return (i === 0 ? v : v.toFixed(1)) + ' ' + u[i]
}

const databaseNote = () => {
  const db = backup.value?.database
  if (!db) return ''
  if (db.backend === 'postgres')
    return 'PostgreSQL —— 将逐表导出为可移植的 SQLite 数据库文件。'
  return 'SQLite —— 磁盘占用 ' + fmtBytes(db.bytes) + '。导出副本会经过压缩整理，体积通常会更小。'
}

function downloadError(e: unknown): void {
  if (e instanceof ApiError && e.status === 409)
    toast('已有备份正在准备中，请稍候。', 'error')
  else toast((e as Error).message || '下载失败', 'error')
}

async function downloadSettings(): Promise<void> {
  if (includeSecrets.value) {
    const ok = await confirm({
      title: '包含敏感凭据',
      message:
        '下载的配置文件将以明文形式包含群晖 NAS 和数据库密码，请务必像保管密码一样妥善存放该文件。',
      okLabel: '包含凭据并下载',
    })
    if (!ok) return
  }
  busyConfig.value = true
  try {
    const name = await downloadFile(
      '/api/backup/config' + (includeSecrets.value ? '?secrets=1' : ''),
      'synopticon-config.toml',
    )
    toast('已保存 ' + name, 'ok')
  } catch (e) {
    downloadError(e)
  } finally {
    busyConfig.value = false
  }
}

async function downloadDatabase(): Promise<void> {
  busyDatabase.value = true
  toast('正在生成数据库快照——图库较大时可能需要片刻。')
  try {
    const name = await downloadFile('/api/backup/database', 'synopticon-backup.db')
    toast('已保存 ' + name, 'ok')
  } catch (e) {
    downloadError(e)
  } finally {
    busyDatabase.value = false
  }
}

onMounted(() => {
  getJSON<BackupInfo>('/api/backup/info')
    .then((info) => (backup.value = info))
    .catch(() => {
      /* the cards still work; only the blurb is missing */
    })
})

function startJob(
  name: string,
  params: Record<string, unknown> = {},
  extra: Record<string, unknown> = {},
): void {
  panel.value?.start(name, params, extra).catch((e: unknown) => {
    if (e instanceof ApiError && e.status === 428) toast('需要确认授权才能继续。', 'error')
    else toast((e as Error).message || '启动任务失败', 'error')
  })
}

function dedupeParams(): Record<string, unknown> {
  const params: Record<string, unknown> = { exact: dedupe.exact, visual: dedupe.visual }
  const t = dedupe.threshold.trim()
  if (t !== '') params.threshold = t
  return params
}

function dedupePreview(): void {
  if (!dedupe.exact && !dedupe.visual) {
    toast('请至少勾选「完全一致」或「视觉相似」之一。', 'error')
    return
  }
  startJob('dedupe', dedupeParams())
}

async function dedupeApply(): Promise<void> {
  if (!dedupe.exact && !dedupe.visual) {
    toast('请至少勾选「完全一致」或「视觉相似」之一。', 'error')
    return
  }
  const ok = await confirm({
    title: '删除重复照片',
    message: '此操作将从群晖 NAS 永久删除重复照片，且无法撤销。',
    phrase: PHRASE_DEDUPE,
    okLabel: '确认删除重复照片',
  })
  if (!ok) return
  const params = dedupeParams()
  params.apply = true
  startJob('dedupe', params, { confirm: true, confirm_phrase: PHRASE_DEDUPE })
}
</script>

<template>
  <div class="page util-page">
    <JobPanel ref="panel" />

    <QuickMerger />

    <section class="card util-card">
      <h3>重复照片去重</h3>
      <p class="muted">
        利用已存哈希清理群晖 NAS 中的重复照片。预演不会修改任何文件；确认删除后会直接从群晖 NAS 永久删除。
      </p>
      <div class="util-opts">
        <label class="opt-check"
          ><input type="checkbox" v-model="dedupe.exact" /> 完全一致（SHA-256 字节相同）</label
        >
        <label class="opt-check"
          ><input type="checkbox" v-model="dedupe.visual" /> 视觉相似（pHash 近似重复）</label
        >
        <div class="opt-row">
          <label for="dd-threshold">汉明距离阈值</label>
          <input
            class="input input-sm"
            id="dd-threshold"
            type="number"
            min="0"
            max="64"
            placeholder="默认"
            v-model="dedupe.threshold"
          />
        </div>
      </div>
      <div class="util-actions">
        <button type="button" class="btn" @click="dedupePreview">预演（不修改群晖）</button>
        <button type="button" class="btn btn-danger" @click="dedupeApply">
          删除重复照片…
        </button>
      </div>
    </section>

    <section class="card util-card">
      <h3>备份系统配置</h3>
      <p class="muted">
        下载当前配置文件。恢复时只需将其放回原路径<template
          v-if="backup?.config"
        >（<code>{{ backup.config.path }}</code
          >）</template
        >即可。
      </p>
      <div class="util-opts">
        <label class="opt-check"
          ><input type="checkbox" v-model="includeSecrets" /> 包含敏感凭据（明文密码）</label
        >
        <p class="muted hint">
          若不勾选，以下敏感字段会被清空，恢复后需重新填写：{{
            backup?.config.secret_keys.join('、') || '所有密码项'
          }}。
        </p>
      </div>
      <div class="util-actions">
        <button type="button" class="btn" :disabled="busyConfig" @click="downloadSettings">
          {{ busyConfig ? '正在准备…' : '下载配置文件' }}
        </button>
      </div>
    </section>

    <section class="card util-card">
      <h3>下载数据库备份</h3>
      <p class="muted">
        导出 Synopticon 本地保存的完整数据副本——包括照片索引、人脸与特征向量、人脸分组、审核记录以及你的账号信息。不会删除任何内容，也不会触碰群晖 NAS。
      </p>
      <p v-if="backup" class="muted">{{ databaseNote() }}</p>
      <div class="util-actions">
        <button type="button" class="btn" :disabled="busyDatabase" @click="downloadDatabase">
          {{ busyDatabase ? '正在准备…' : '下载数据库' }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.util-page {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.util-card {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.util-card h3 {
  margin: 0;
}
.util-opts {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.util-opts .opt-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.util-opts label {
  font-size: var(--fs-sm);
}
.opt-check {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}
.util-actions {
  display: flex;
  gap: var(--sp-2);
  padding-top: var(--sp-2);
}
.util-opts .hint {
  margin: 0;
  font-size: var(--fs-sm);
}
</style>
