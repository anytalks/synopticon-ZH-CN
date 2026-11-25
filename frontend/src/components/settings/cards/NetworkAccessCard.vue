<script setup lang="ts">
// The primary UI for network access (SEC2). The Security tab's `allow_from` /
// `allow_private_networks` / `trusted_proxies` fields (rendered by SchemaForm)
// are the raw escape hatch; this card is the diagnostic that tells an operator
// whether flipping them is even safe from where they are sitting right now.
//
// Reads GET /api/security/access (route 17, in-memory + one-scope, no
// connection) for "this browser" and the proxy-trust hazard readout, and GET
// /api/config for the saved (on-disk) security values so the "not in effect
// until restart" line can compare them against what the running middleware is
// actually using. Nothing here decides anything -- every field is a diagnostic
// (clientip.py RULE 2) and the banners below are ordered by how bad the
// misconfiguration they describe actually is, not by when they were added.
import { computed, onMounted, ref } from 'vue'
import { getJSON, ApiError } from '../../../api/client'

interface AllowlistInfo {
  active: boolean
  entries: string[]
  allow_private: boolean
  loopback_always: boolean
  adds_nothing: boolean
}

interface AccessInfo {
  client_ip: string
  effective_source: 'forwarded' | 'socket_peer'
  peer: string
  allowed: boolean
  allowlist: AllowlistInfo
  effective: { summary: string; list_adds_nothing: boolean }
  proxy: {
    trusted_proxies: string[]
    peer_is_trusted_proxy: boolean
    forwarded_for_present: boolean
    forwarded_for_raw: string
    trusts_loopback: boolean
    shared_bucket: boolean
  }
  in_effect: {
    allow_from: string[]
    allow_private_networks: boolean
    trusted_proxies: string[]
  }
}

interface SecuritySaved {
  allow_from?: string[]
  allow_private_networks?: boolean
  trusted_proxies?: string[]
}

const access = ref<AccessInfo | null>(null)
const saved = ref<SecuritySaved | null>(null)
const loadError = ref('')
const loading = ref(false)

function sameList(a: string[] | undefined, b: string[] | undefined): boolean {
  const x = a || []
  const y = b || []
  return x.length === y.length && x.every((v, i) => v === y[i])
}

const savedDiffersFromRunning = computed(() => {
  if (!access.value || !saved.value) return false
  const s = saved.value
  const eff = access.value.in_effect
  return (
    !sameList(s.allow_from, eff.allow_from) ||
    !!s.allow_private_networks !== eff.allow_private_networks ||
    !sameList(s.trusted_proxies, eff.trusted_proxies)
  )
})

const effectiveSummary = computed(() => {
  const a = access.value
  if (!a) return ''
  const entries = a.allowlist.entries
  if (entries.length) {
    const bits = [...entries]
    if (a.allowlist.allow_private) bits.push('所有局域网')
    bits.push('本机（localhost）')
    return `当前允许访问：${bits.join('、')}。`
  }
  return '当前允许所有地址访问。'
})

async function load(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const [a, cfg] = await Promise.all([
      getJSON<AccessInfo>('/api/security/access'),
      getJSON<{ values: { security?: SecuritySaved } }>('/api/config'),
    ])
    access.value = a
    saved.value = cfg.values?.security || null
  } catch (err) {
    loadError.value = err instanceof ApiError ? err.message : '无法加载网络访问状态'
  } finally {
    loading.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="card access-section network-access">
    <h3>网络访问控制</h3>

    <p v-if="loading && !access" class="muted">正在检查…</p>
    <p v-else-if="loadError" class="muted error-text">{{ loadError }}</p>

    <template v-else-if="access">
      <div v-if="access.proxy.trusts_loopback" class="banner banner-danger">
        Synopticon 当前信任来自本机连接中的 X-Forwarded-For 请求头。你的反向代理<strong>必须</strong>覆盖该请求头——例如在 nginx 中配置
        <code>proxy_set_header X-Forwarded-For $remote_addr;</code>（Caddy 和 Traefik 默认已做此处理）。如果代理直接透传访客自带的请求头（例如未加配置的裸
        <code>proxy_pass</code>），任何访客都可以伪造任意 IP 地址，从而绕过允许访问列表和按 IP 统计的登录限流。Synopticon 无法从服务端区分这两种情况，请务必核查反向代理配置。
      </div>

      <div
        v-else-if="
          access.proxy.forwarded_for_present &&
          !access.proxy.peer_is_trusted_proxy &&
          access.allowlist.active
        "
        class="banner banner-danger"
      >
        当前请求经过了一个未列在 <code>trusted_proxies</code> 中的代理服务器，因此所有访客看起来都来自同一个地址，下方的允许访问列表实际上无法起到限制作用。
      </div>

      <div v-else-if="access.proxy.shared_bucket" class="banner banner-warn">
        你的反向代理运行在本机且未传递真实访客地址，导致所有人（包括外部陌生访客）均显示为 127.0.0.1。此时允许访问列表无法限制任何访问，按地址统计的登录限流也会将所有访客合并计数。请配置反向代理以覆盖 X-Forwarded-For 请求头。
      </div>

      <div v-if="access.effective.list_adds_nothing" class="banner banner-warn">
        当前允许列表中的所有地址均已被「始终允许局域网访问」覆盖——该列表目前尚未限制任何地址。
      </div>

      <div v-if="savedDiffersFromRunning" class="banner banner-info">
        配置已保存，但需重启 Web 服务后才会生效——「安全设置」显示的是磁盘上已保存的配置，本面板显示的是当前运行中的策略。
      </div>

      <p class="summary">{{ effectiveSummary }}</p>

      <table class="data browser-table">
        <tbody>
          <tr>
            <th>当前浏览器</th>
            <td class="mono">{{ access.client_ip }}</td>
          </tr>
          <tr>
            <th>连接方式</th>
            <td>
              {{ access.effective_source === 'forwarded' ? '经由受信任的反向代理' : '直连' }}
            </td>
          </tr>
          <tr>
            <th>直连对端地址</th>
            <td class="mono">{{ access.peer }}</td>
          </tr>
          <tr v-if="access.proxy.forwarded_for_present">
            <th>收到的 X-Forwarded-For</th>
            <td class="mono">{{ access.proxy.forwarded_for_raw }}</td>
          </tr>
        </tbody>
      </table>

      <p class="muted small">
        请在「安全设置」标签页中修改允许访问列表和「始终允许局域网访问」；如果使用了反向代理，也请在那里配置
        <code>trusted_proxies</code>。若不慎被锁定在外，请在服务器上运行
        <code>synopticon web-access --clear</code>，然后重启 Synopticon。
      </p>

      <button class="btn btn-sm" type="button" :disabled="loading" @click="load">
        刷新
      </button>
    </template>
  </div>
</template>

<style scoped>
.network-access {
  max-width: 640px;
}
.summary {
  margin: var(--sp-2) 0;
}
.banner {
  border-left: 3px solid var(--action);
  border-radius: var(--radius);
  background: var(--bg-sunken);
  padding: var(--sp-2) var(--sp-3);
  margin-bottom: var(--sp-2);
  font-size: var(--fs-sm);
  line-height: 1.5;
}
.banner-danger {
  border-left-color: var(--danger);
}
.banner-warn {
  border-left-color: var(--warn);
}
.banner-info {
  border-left-color: var(--action);
}
.banner code {
  font-family: ui-monospace, monospace;
  font-size: 0.9em;
}
.browser-table {
  margin: var(--sp-3) 0;
  width: auto;
}
.browser-table th {
  text-align: left;
  padding: var(--sp-1) var(--sp-3) var(--sp-1) 0;
  color: var(--text-2);
  font-weight: normal;
  white-space: nowrap;
}
.browser-table td {
  padding: var(--sp-1) 0;
}
.small {
  font-size: var(--fs-sm);
}
.error-text {
  color: var(--danger);
}
</style>
