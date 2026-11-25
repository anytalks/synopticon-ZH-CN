<script setup lang="ts">
// Login throttling (SEC5): a live readout of route 19's limiter.snapshot(),
// with a per-row "Clear" wired to route 20. Two tiers only, both always
// armed on every address -- there is no global tier and no exempt address
// (D5, D6), which is why the card says so in its own copy rather than
// letting an operator infer a carve-out that does not exist.
import { onMounted, ref } from 'vue'
import { getJSON, postJSON, ApiError } from '../../../api/client'
import { toast } from '../../../stores/toasts'

interface ThrottlePairRow {
  scope: string
  ip: string
  username: string
  failures: number
  attempts: number
  locked_for: number
  forget_in: number
}

interface ThrottleAddressRow {
  ip: string
  failures_in_window: number
  blocked_for: number
}

interface ThrottleSnapshot {
  pairs: ThrottlePairRow[]
  ips: ThrottleAddressRow[]
  tracked: number
  max_tracked: number
  thresholds: { pair_max_attempts: number; ip_max_failures: number }
}

const SCOPE_LABELS: Record<string, string> = {
  password: '密码登录',
  totp: '两步验证码',
  change_password: '修改密码',
  reauth: '重新验证身份',
}

const snap = ref<ThrottleSnapshot | null>(null)
const loadFailed = ref(false)
const clearing = ref('') // "" | "pair:<scope>:<ip>:<username>" | "ip:<ip>"

function scopeLabel(scope: string): string {
  return SCOPE_LABELS[scope] || scope
}

function fmtDuration(seconds: number): string {
  if (seconds <= 0) return '—'
  if (seconds < 60) return `${seconds} 秒`
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return s ? `${m} 分 ${s} 秒` : `${m} 分钟`
}

function errMsg(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback
  return (err as Error)?.message || fallback
}

async function load(): Promise<void> {
  try {
    snap.value = await getJSON<ThrottleSnapshot>('/api/security/throttles')
    loadFailed.value = false
  } catch {
    loadFailed.value = true
  }
}

async function clear(body: { ip: string } | { username: string }, token: string): Promise<void> {
  clearing.value = token
  try {
    const res = await postJSON<{ ok: true; cleared: number }>('/api/security/throttles/clear', body)
    toast(res.cleared > 0 ? `已清除 ${res.cleared} 条限流记录` : '没有可清除的记录', 'ok')
    await load()
  } catch (err) {
    toast(errMsg(err, '无法清除限流记录'), 'error')
  } finally {
    clearing.value = ''
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="card throttle-section">
    <h3>登录限流</h3>
    <p class="muted">
      失败或未完成的登录尝试会按账号和 IP 地址分别限流。该策略对访问 Synopticon 的所有地址生效（包括本机），不存在豁免地址，除调整下方阈值外无法关闭。
    </p>

    <template v-if="snap">
      <p class="muted counts">
        当前追踪 {{ snap.tracked }} / {{ snap.max_tracked }} 条记录 · 单账号上限
        {{ snap.thresholds.pair_max_attempts }} 次尝试 · 单地址上限
        {{ snap.thresholds.ip_max_failures }} 次失败
      </p>

      <h4>已锁定账号</h4>
      <p v-if="!snap.pairs.length" class="muted">当前没有被锁定的账号。</p>
      <div v-else class="table-scroll">
        <table class="data">
          <thead>
            <tr>
              <th>验证环节</th>
              <th>IP 地址</th>
              <th>用户名</th>
              <th>失败 / 尝试</th>
              <th>剩余锁定</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in snap.pairs" :key="`${p.scope}:${p.ip}:${p.username}`">
              <td>{{ scopeLabel(p.scope) }}</td>
              <td class="mono">{{ p.ip }}</td>
              <td>{{ p.username }}</td>
              <td>{{ p.failures }} / {{ p.attempts }}</td>
              <td>{{ fmtDuration(p.locked_for) }}</td>
              <td>
                <button
                  class="btn btn-sm btn-ghost"
                  type="button"
                  :disabled="clearing !== ''"
                  @click="clear({ username: p.username }, `pair:${p.username}`)"
                >
                  {{ clearing === `pair:${p.username}` ? '清除中…' : '解除账号限制' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <h4>已拦截地址</h4>
      <p v-if="!snap.ips.length" class="muted">当前没有被拦截的地址。</p>
      <div v-else class="table-scroll">
        <table class="data">
          <thead>
            <tr>
              <th>IP 地址</th>
              <th>时间窗内失败次数</th>
              <th>剩余拦截</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in snap.ips" :key="row.ip">
              <td class="mono">{{ row.ip }}</td>
              <td>{{ row.failures_in_window }}</td>
              <td>{{ fmtDuration(row.blocked_for) }}</td>
              <td>
                <button
                  class="btn btn-sm btn-ghost"
                  type="button"
                  :disabled="clearing !== ''"
                  @click="clear({ ip: row.ip }, `ip:${row.ip}`)"
                >
                  {{ clearing === `ip:${row.ip}` ? '清除中…' : '解除地址限制' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <p class="muted recovery">
        如果自己的地址不慎被锁定，可在 <code>config.toml</code> 的 <code>[security]</code> 下设置
        <code>max_failures_per_address = 0</code> 并重启 Synopticon，或在上方直接清除对应条目。
      </p>
    </template>
    <p v-else-if="loadFailed" class="muted">无法加载登录限流状态。</p>
  </div>
</template>

<style scoped>
.throttle-section {
  max-width: 720px;
}
.throttle-section h4 {
  margin: var(--sp-4) 0 var(--sp-1);
  font-size: var(--fs-base);
}
.counts {
  margin-top: var(--sp-2);
}
.table-scroll {
  overflow-x: auto;
}
.recovery {
  margin-top: var(--sp-3);
}
.recovery code {
  font-family: ui-monospace, monospace;
}
</style>
