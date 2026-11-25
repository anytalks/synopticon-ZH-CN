<script setup lang="ts">
// Full-access API keys for automation. A newly created key's secret comes back
// exactly once (the server only stores its hash), so it stays on screen until
// the next create; revoking gates on a confirm.
import { onMounted, ref } from 'vue'
import { getJSON, postJSON, ApiError } from '../../../api/client'
import type { ApiKey } from '../../../api/types'
import { toast } from '../../../stores/toasts'
import { confirm } from '../../../composables/useConfirm'

const keys = ref<ApiKey[]>([])
const keyName = ref('')
const revealedKey = ref('')

function fmtTime(t: number | null | undefined): string {
  return t ? new Date(t * 1000).toLocaleString('zh-CN') : '—'
}

function errMsg(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback
  return (err as Error)?.message || fallback
}

async function load(): Promise<void> {
  try {
    const data = await getJSON<{ keys: ApiKey[] }>('/api/auth/keys')
    keys.value = data.keys || []
  } catch {
    /* transient — leave the current list */
  }
}

async function createKey(): Promise<void> {
  const name = keyName.value.trim()
  if (!name) return
  try {
    const res = await postJSON<{ key: string; name: string }>('/api/auth/keys', { name })
    keyName.value = ''
    revealedKey.value = res.key
    void load()
  } catch (err) {
    toast(errMsg(err, '无法创建密钥'), 'error')
  }
}

async function revokeKey(id: number, name: string): Promise<void> {
  const ok = await confirm({
    title: '吊销 API 密钥',
    message: `确定要吊销“${name}”吗？所有使用该密钥的客户端将立即失效。`,
    okLabel: '吊销',
  })
  if (!ok) return
  try {
    await postJSON(`/api/auth/keys/${id}/revoke`, {})
    toast('密钥已吊销', 'ok')
    void load()
  } catch (err) {
    toast(errMsg(err, '吊销失败'), 'error')
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="card keys-section">
    <h3>API 密钥</h3>
    <p class="muted">
      供自动化脚本或外部工具（如配套扩展）使用的完全访问权限密钥。密钥明文仅显示一次。
    </p>
    <form class="key-form" @submit.prevent="createKey">
      <label style="flex: 1"
        >密钥名称
        <input class="input" type="text" placeholder="例如：自动化脚本" required v-model="keyName" />
      </label>
      <button class="btn btn-action" type="submit">创建密钥</button>
    </form>
    <div v-if="revealedKey" class="key-reveal">
      新密钥（请立即复制，关闭后将不再显示）：<br />{{ revealedKey }}
    </div>
    <table class="data key-table">
      <thead>
        <tr>
          <th>名称</th>
          <th>前缀</th>
          <th>创建时间</th>
          <th>最近使用</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="k in keys" :key="k.id" :class="{ revoked: k.revoked }">
          <td>{{ k.name }}</td>
          <td class="mono">{{ k.key_prefix }}…</td>
          <td>{{ fmtTime(k.created_at) }}</td>
          <td>{{ fmtTime(k.last_used_at) }}</td>
          <td>
            <button
              v-if="!k.revoked"
              class="btn btn-sm btn-danger"
              type="button"
              @click="revokeKey(k.id, k.name)"
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
.keys-section {
  max-width: 640px;
}
.key-form {
  display: flex;
  flex-direction: row;
  align-items: flex-end;
  gap: var(--sp-2);
  max-width: 380px;
  margin-top: var(--sp-3);
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.key-table {
  width: 100%;
  margin-top: var(--sp-3);
}
.key-table tr.revoked td {
  opacity: 0.5;
}
.key-reveal {
  margin-top: var(--sp-2);
  font-family: ui-monospace, monospace;
  background: var(--bg-sunken);
  border: 1px solid var(--action);
  border-radius: var(--radius);
  padding: var(--sp-2) var(--sp-3);
  word-break: break-all;
}
</style>
