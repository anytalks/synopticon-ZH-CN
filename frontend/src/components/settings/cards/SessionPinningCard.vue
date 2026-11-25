<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { getJSON, postJSON, ApiError } from '../../../api/client'
import { toast } from '../../../stores/toasts'

interface Observed {
  user_agent: string
  device_key: string
  ip: string
  network: string
}

interface PinningInfo {
  mode: string
  modes: string[]
  session_pinned: boolean
  other_sessions: number
  observed: Observed
}

interface Me {
  totp_enabled: boolean | null
}

const MODE_LABELS: Record<string, string> = {
  off: '关闭',
  device: '绑定当前设备',
  'device+network': '绑定当前设备与网络',
}

const info = ref<PinningInfo | null>(null)
const totpEnabled = ref(false)
const selectedMode = ref('off')
const form = reactive({ password: '', code: '' })
const saving = ref(false)
const loadFailed = ref(false)

function modeLabel(mode: string): string {
  return MODE_LABELS[mode] || mode
}

async function load(): Promise<void> {
  try {
    const [pinning, me] = await Promise.all([
      getJSON<PinningInfo>('/api/auth/session-pinning'),
      getJSON<Me>('/api/auth/me'),
    ])
    info.value = pinning
    selectedMode.value = pinning.mode
    totpEnabled.value = !!me.totp_enabled
    loadFailed.value = false
  } catch {
    loadFailed.value = true
  }
}

function errMsg(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback
  return (err as Error)?.message || fallback
}

async function save(): Promise<void> {
  if (!form.password) {
    toast('请输入密码以确认此更改', 'error')
    return
  }
  saving.value = true
  try {
    const body: Record<string, string> = { mode: selectedMode.value, password: form.password }
    if (form.code) body.code = form.code
    const res = await postJSON<{ ok: true; mode: string; signed_out_others: number }>(
      '/api/auth/session-pinning',
      body,
    )
    form.password = ''
    form.code = ''
    const others =
      res.signed_out_others > 0
        ? `——已将其余 ${res.signed_out_others} 个会话退出登录`
        : ''
    toast(`会话绑定已设为「${modeLabel(res.mode)}」${others}`, 'ok')
    await load()
  } catch (err) {
    toast(errMsg(err, '无法更新会话绑定设置'), 'error')
  } finally {
    saving.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="card pinning-section">
    <h3>会话绑定</h3>
    <p class="muted">
      将当前登录会话绑定到发起登录的浏览器（以及可选的所在网络），防止 Cookie 被复制或窃取后在其他地方使用。<br><br>
      请结合自身安全需求评估是否需要防范会话劫持——对大多数用户而言，开启两步验证已能提供足够防护。首次开启会话绑定时，系统会将当前账号下的其余所有会话退出登录。
    </p>

    <template v-if="info">
      <dl class="observed">
        <dt>当前浏览器</dt>
        <dd>{{ info.observed.user_agent || '—' }} <span class="mono">({{ info.observed.device_key }})</span></dd>
        <dt>当前地址</dt>
        <dd>{{ info.observed.ip }} <span class="mono">({{ info.observed.network }})</span></dd>
        <dt>其他已登录会话</dt>
        <dd>{{ info.other_sessions }}</dd>
      </dl>

      <form class="pinning-form" @submit.prevent="save">
        <label>
          会话绑定策略
          <select class="input" v-model="selectedMode">
            <option v-for="m in info.modes" :key="m" :value="m">{{ modeLabel(m) }}</option>
          </select>
        </label>
        <p v-if="selectedMode === 'device+network'" class="warning">
          不建议在移动网络或 IPv4/IPv6 双栈环境下使用——只要网络切换，你就会被自动退出登录。
        </p>

        <label>
          当前密码
          <input class="input" type="password" autocomplete="current-password" v-model="form.password" required />
        </label>
        <label v-if="totpEnabled">
          两步验证码（或备用恢复码）
          <input class="input" type="text" inputmode="numeric" autocomplete="one-time-code" v-model="form.code" />
        </label>

        <button class="btn btn-primary" type="submit" :disabled="saving">
          {{ saving ? '正在保存…' : '保存' }}
        </button>
      </form>

      <p class="muted recovery">
        如果因浏览器或网络频繁变更而被意外退出登录，可在服务器上运行
        <code>synopticon session-pin off</code> 直接为账号关闭会话绑定，无需先登录界面。
      </p>
    </template>
    <p v-else-if="loadFailed" class="muted">无法加载会话绑定设置。</p>
  </div>
</template>

<style scoped>
.pinning-section {
  max-width: 640px;
}
.observed {
  display: grid;
  grid-template-columns: max-content 1fr;
  gap: var(--sp-1) var(--sp-3);
  font-size: var(--fs-sm);
  margin: var(--sp-3) 0;
}
.observed dt {
  color: var(--text-2);
}
.observed dd {
  margin: 0;
}
.pinning-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  max-width: 380px;
  margin-top: var(--sp-3);
}
.pinning-form label {
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.warning {
  color: var(--danger);
  font-size: var(--fs-sm);
  margin: 0;
}
.recovery {
  margin-top: var(--sp-3);
}
.recovery code {
  font-family: ui-monospace, monospace;
}
</style>
