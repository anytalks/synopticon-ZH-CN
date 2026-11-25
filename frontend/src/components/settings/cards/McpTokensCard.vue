<script setup lang="ts">
// Scoped tokens for AI agents on /mcp. Like API keys, the secret comes back
// exactly once; the scope catalogue (labels, descriptions, requirements) is the
// server's, so a new scope needs no change here.
import { computed, onMounted, ref } from 'vue'
import { getJSON, postJSON, ApiError } from '../../../api/client'
import type { McpScope, McpStatus, McpToken } from '../../../api/types'
import { toast } from '../../../stores/toasts'
import { confirm } from '../../../composables/useConfirm'

const status = ref<McpStatus | null>(null)
const tokens = ref<McpToken[]>([])
const tokenName = ref('')
const picked = ref<Set<string>>(new Set(['read']))
const revealed = ref<{ token: string; name: string } | null>(null)

const scopes = computed<McpScope[]>(() => status.value?.scopes ?? [])
const scopeById = computed(() => new Map(scopes.value.map((s) => [s.id, s])))
const endpointUrl = computed(() => window.location.origin + (status.value?.endpoint || '/mcp'))

const cliSnippet = computed(() =>
  revealed.value
    ? `claude mcp add --transport http synopticon ${endpointUrl.value} --header "Authorization: Bearer ${revealed.value.token}"`
    : '',
)
const jsonSnippet = computed(() =>
  revealed.value
    ? JSON.stringify(
        {
          mcpServers: {
            synopticon: {
              type: 'http',
              url: endpointUrl.value,
              headers: { Authorization: `Bearer ${revealed.value.token}` },
            },
          },
        },
        null,
        2,
      )
    : '',
)

const SCOPE_COPY: Record<string, { label: string; description: string }> = {
  read: {
    label: '只读查看',
    description:
      '查看系统状态、配置、任务日志、审核队列，以及人脸检测与聚类诊断信息（包含人脸头像与照片预览）。默认始终授予。',
  },
  config: {
    label: '调整算法参数',
    description:
      '修改「推理与加速」「人脸检测」「画质修复」「聚类分组」和「比对与建议」设置。不可修改群晖连接、存储与缓存、数据库、安全设置或 MCP 接口配置。',
  },
  jobs: {
    label: '运行处理流程',
    description:
      '启动或取消同步图库、人脸检测与提取、人脸聚类分组、报告生成、重建头像、性能基准与下载模型，以及写回群晖和重复照片去重的预演。均不会修改群晖 NAS。',
  },
  review: {
    label: '处理审核建议',
    description:
      '在审核队列中通过、拒绝、隐藏或重置识别建议。在执行写回操作前，任何更改都不会同步到群晖 NAS。',
  },
  maintenance: {
    label: '维护清理',
    description:
      '清空审核队列或待写回记录、清理失效审核项、删除人脸头像缓存以及重置本地衍生数据（不包含完全重置）。',
  },
  apply: {
    label: '写回群晖',
    description: '将已通过的归属认领、低置信度复核和发现新人物建议写回群晖照片。',
  },
  'apply:reassign': {
    label: '写回改判人物',
    description: '同时允许将群晖照片中已标记归属的人脸移动至其他人物。',
  },
  'apply:merge': {
    label: '写回合并未命名分组',
    description: '同时允许将未命名人物合并到其他人物。AI 代理永远不能合并两个已命名人物。',
  },
}

function scopeLabel(id: string, fallback?: string): string {
  return SCOPE_COPY[id]?.label ?? fallback ?? id
}

function scopeDesc(s: McpScope): string {
  return SCOPE_COPY[s.id]?.description ?? s.description
}

function fmtTime(t: number | null | undefined): string {
  return t ? new Date(t * 1000).toLocaleString('zh-CN') : '—'
}

function errMsg(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback
  return (err as Error)?.message || fallback
}

function isNas(id: string): boolean {
  return scopeById.value.get(id)?.danger === 'nas'
}

function toggle(scope: McpScope, on: boolean): void {
  if (scope.id === 'read') return
  const next = new Set(picked.value)
  if (on) {
    next.add(scope.id)
    for (const r of scope.requires) next.add(r)
  } else {
    next.delete(scope.id)
    // Unchecking a scope unchecks everything that needs it, transitively.
    let changed = true
    while (changed) {
      changed = false
      for (const s of scopes.value) {
        if (next.has(s.id) && s.requires.some((r) => !next.has(r))) {
          next.delete(s.id)
          changed = true
        }
      }
    }
  }
  picked.value = next
}

async function load(): Promise<void> {
  try {
    const [st, tk] = await Promise.all([
      getJSON<McpStatus>('/api/mcp/status'),
      getJSON<{ tokens: McpToken[] }>('/api/mcp/tokens'),
    ])
    status.value = st
    tokens.value = tk.tokens || []
  } catch {
    /* transient — leave the current state */
  }
}

async function createToken(): Promise<void> {
  const name = tokenName.value.trim()
  if (!name) return
  try {
    const res = await postJSON<{ token: string; name: string }>('/api/mcp/tokens', {
      name,
      scopes: [...picked.value],
    })
    tokenName.value = ''
    picked.value = new Set(['read'])
    revealed.value = { token: res.token, name: res.name }
    void load()
  } catch (err) {
    toast(errMsg(err, '无法创建令牌'), 'error')
  }
}

async function revokeToken(id: number, name: string): Promise<void> {
  const ok = await confirm({
    title: '吊销 MCP 令牌',
    message: `确定要吊销“${name}”吗？所有使用该令牌的 AI 代理将立即无法连接。`,
    okLabel: '吊销',
  })
  if (!ok) return
  try {
    await postJSON(`/api/mcp/tokens/${id}/revoke`, {})
    toast('令牌已吊销', 'ok')
    void load()
  } catch (err) {
    toast(errMsg(err, '吊销失败'), 'error')
  }
}

async function copy(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    toast('已复制', 'ok')
  } catch {
    /* clipboard access denied — the text is already selectable */
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="card mcp-section">
    <h3>MCP 访问令牌</h3>
    <p class="muted">
      带有权限范围限制的令牌，可让 AI 代理通过 Synopticon 的 MCP 接口调整配置、排查人脸检测与聚类问题并执行处理步骤。此类令牌仅可用于 MCP 接口，密钥明文仅显示一次。
    </p>
    <p v-if="status && status.enabled" class="mcp-state">
      <span class="badge state-running">已启用</span>
      接口地址：<span class="mono">{{ endpointUrl }}</span>
    </p>
    <p v-else-if="status" class="mcp-state">
      <span class="badge">未启用</span>
      请前往「系统设置 → MCP 接口」开启连接权限并重启 Synopticon。在此之前你也可以预先创建令牌。
    </p>

    <form class="mcp-form" @submit.prevent="createToken">
      <label
        >令牌名称
        <input
          class="input"
          type="text"
          placeholder="例如：claude-code-laptop"
          required
          v-model="tokenName"
        />
      </label>
      <fieldset class="scope-list">
        <legend>权限范围</legend>
        <label v-for="s in scopes" :key="s.id" class="scope-row" :class="{ nas: s.danger === 'nas' }">
          <input
            type="checkbox"
            :checked="picked.has(s.id)"
            :disabled="s.id === 'read'"
            @change="toggle(s, ($event.target as HTMLInputElement).checked)"
          />
          <span>
            <strong>{{ scopeLabel(s.id, s.label) }}</strong>
            <span v-if="s.danger === 'nas'" class="badge danger-badge">可写入群晖</span>
            <span class="muted scope-desc">{{ scopeDesc(s) }}</span>
          </span>
        </label>
      </fieldset>
      <p class="muted">
        AI 代理永远无法执行合并已命名人物、删除重复照片或完全重置操作；这些高风险操作仅限在 Web 界面中手动进行。
      </p>
      <div>
        <button class="btn btn-action" type="submit">创建令牌</button>
      </div>
    </form>

    <div v-if="revealed" class="mcp-reveal">
      <div>
        为“{{ revealed.name }}”创建的新令牌（请立即复制，之后将不再显示）：
        <div class="snippet">{{ revealed.token }}</div>
        <button class="btn btn-sm" type="button" @click="copy(revealed.token)">复制令牌</button>
      </div>
      <div>
        Claude Code 命令：
        <pre class="snippet">{{ cliSnippet }}</pre>
        <button class="btn btn-sm" type="button" @click="copy(cliSnippet)">复制命令</button>
      </div>
      <div>
        其他客户端（Streamable HTTP）：
        <pre class="snippet">{{ jsonSnippet }}</pre>
        <button class="btn btn-sm" type="button" @click="copy(jsonSnippet)">复制 JSON</button>
      </div>
    </div>

    <table class="data mcp-table">
      <thead>
        <tr>
          <th>名称</th>
          <th>前缀</th>
          <th>权限范围</th>
          <th>创建时间</th>
          <th>最近使用</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in tokens" :key="t.id" :class="{ revoked: t.revoked }">
          <td>{{ t.name }}</td>
          <td class="mono">{{ t.token_prefix }}…</td>
          <td>
            <span
              v-for="sc in t.scopes"
              :key="sc"
              class="badge scope-chip"
              :class="{ 'danger-badge': isNas(sc) }"
              :title="sc"
              >{{ scopeLabel(sc) }}</span
            >
          </td>
          <td>{{ fmtTime(t.created_at) }}</td>
          <td>{{ fmtTime(t.last_used_at) }}</td>
          <td>
            <button
              v-if="!t.revoked"
              class="btn btn-sm btn-danger"
              type="button"
              @click="revokeToken(t.id, t.name)"
            >
              吊销
            </button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.mcp-section {
  max-width: 760px;
}
.mcp-state {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}
.mcp-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  max-width: 560px;
  margin-top: var(--sp-3);
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.scope-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  border: 1px solid var(--border-soft);
  border-radius: var(--radius);
  padding: var(--sp-2) var(--sp-3);
}
.scope-row {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
}
.scope-desc {
  display: block;
}
.danger-badge {
  background: rgba(216, 67, 67, 0.14);
  color: var(--danger);
  border-color: transparent;
  margin-left: var(--sp-2);
}
.scope-chip {
  margin: 0 4px 4px 0;
}
.scope-chip.danger-badge {
  margin-left: 0;
}
.mcp-table {
  width: 100%;
  margin-top: var(--sp-3);
}
.mcp-table tr.revoked td {
  opacity: 0.5;
}
.mcp-reveal {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  margin-top: var(--sp-3);
  border: 1px solid var(--action);
  border-radius: var(--radius);
  padding: var(--sp-2) var(--sp-3);
}
.snippet {
  font-family: ui-monospace, monospace;
  background: var(--bg-sunken);
  border-radius: var(--radius);
  padding: var(--sp-2) var(--sp-3);
  margin: var(--sp-1) 0;
  word-break: break-all;
  white-space: pre-wrap;
}
</style>
