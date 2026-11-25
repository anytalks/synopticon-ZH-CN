<script setup lang="ts">
// Two-step sign-in (SEC1): enrol, confirm, regenerate backup codes, disable.
//
// There is no server-side QR (D1): route 11 hands back the otpauth:// URI and
// the base32 secret, and this component draws the symbol itself with `uqr`.
// `renderSVG` returns a plain string, wrapped into a data URI and bound to an
// <img> rather than injected with v-html -- an <img> needs no HTML injection
// surface at all.
import { computed, onMounted, reactive, ref } from 'vue'
import { renderSVG } from 'uqr'
import { getJSON, postJSON, ApiError } from '../../../api/client'
import { toast } from '../../../stores/toasts'

interface TotpStatus {
  enrolled: boolean
  pending: boolean
  confirmed_at: number | null
  recovery_remaining: number
  recovery_generated_at: number | null
  pending_expires_in: number | null
}

interface TotpStartResponse {
  secret: string
  secret_groups: string
  otpauth_uri: string
  pending_expires_in: number
  manual: { issuer: string; account: string; algorithm: string; digits: number; period: number }
}

const status = ref<TotpStatus | null>(null)
const pending = ref<TotpStartResponse | null>(null)
const qrSrc = ref<string | null>(null)
const qrFailed = ref(false)

const startPassword = ref('')
const confirmCode = ref('')
const recoveryCodes = ref<string[] | null>(null)

const showDisableForm = ref(false)
const disableForm = reactive({ password: '', code: '' })

const showRegenForm = ref(false)
const regenForm = reactive({ password: '', code: '' })

const busy = ref(false)

function errMsg(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    if (err.status === 429) {
      const retry = (err.body as { retry_after?: number } | null)?.retry_after
      return retry
        ? `尝试次数过多——请在 ${retry} 秒后重试。`
        : err.message || '尝试次数过多——请稍后重试。'
    }
    return err.message || fallback
  }
  return (err as Error)?.message || fallback
}

function fmtTime(t: number | null | undefined): string {
  return t ? new Date(t * 1000).toLocaleString('zh-CN') : '—'
}

const minutesLeft = computed(() => {
  const secs = status.value?.pending_expires_in ?? pending.value?.pending_expires_in
  return secs != null ? Math.max(1, Math.ceil(secs / 60)) : null
})

function renderQr(uri: string): void {
  try {
    const svg = renderSVG(uri, { ecc: 'M', border: 4, pixelSize: 6 })
    // btoa only accepts Latin1; the URI-encode/unescape round trip is the
    // standard way to base64 a UTF-8 string in the browser.
    qrSrc.value = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`
    qrFailed.value = false
  } catch {
    qrSrc.value = null
    qrFailed.value = true
  }
}

async function loadStatus(): Promise<void> {
  try {
    status.value = await getJSON<TotpStatus>('/api/auth/totp')
  } catch {
    /* transient — leave the current view */
  }
}

async function startEnrolment(fresh: boolean): Promise<void> {
  if (!startPassword.value) {
    toast('请输入密码以继续', 'error')
    return
  }
  busy.value = true
  try {
    const url = fresh ? '/api/auth/totp/start?fresh=1' : '/api/auth/totp/start'
    const res = await postJSON<TotpStartResponse>(url, { password: startPassword.value })
    pending.value = res
    startPassword.value = ''
    confirmCode.value = ''
    renderQr(res.otpauth_uri)
  } catch (err) {
    toast(errMsg(err, '无法开始设置'), 'error')
  } finally {
    busy.value = false
  }
}

async function confirmEnrolment(): Promise<void> {
  if (!confirmCode.value) return
  busy.value = true
  try {
    const res = await postJSON<{ ok: true; recovery_codes: string[] }>(
      '/api/auth/totp/confirm',
      { code: confirmCode.value },
    )
    recoveryCodes.value = res.recovery_codes
    pending.value = null
    qrSrc.value = null
    confirmCode.value = ''
    toast('两步验证已开启', 'ok')
    await loadStatus()
  } catch (err) {
    toast(errMsg(err, '验证码无效'), 'error')
  } finally {
    busy.value = false
  }
}

async function submitDisable(): Promise<void> {
  busy.value = true
  try {
    await postJSON('/api/auth/totp/disable', {
      password: disableForm.password,
      code: disableForm.code,
    })
    disableForm.password = ''
    disableForm.code = ''
    showDisableForm.value = false
    recoveryCodes.value = null
    toast('两步验证已关闭', 'ok')
    await loadStatus()
  } catch (err) {
    toast(errMsg(err, '密码或验证码无效'), 'error')
  } finally {
    busy.value = false
  }
}

async function submitRegen(): Promise<void> {
  busy.value = true
  try {
    const res = await postJSON<{ codes: string[] }>('/api/auth/totp/recovery-codes', {
      password: regenForm.password,
      code: regenForm.code,
    })
    recoveryCodes.value = res.codes
    regenForm.password = ''
    regenForm.code = ''
    showRegenForm.value = false
    toast('已生成新的备用恢复码', 'ok')
    await loadStatus()
  } catch (err) {
    toast(errMsg(err, '密码或验证码无效'), 'error')
  } finally {
    busy.value = false
  }
}

async function copySecret(): Promise<void> {
  if (!pending.value) return
  try {
    await navigator.clipboard.writeText(pending.value.secret_groups)
    toast('已复制', 'ok')
  } catch {
    /* clipboard access denied — the text is already selectable */
  }
}

onMounted(async () => {
  await loadStatus()
  // A reload mid-enrolment: the card cannot show the QR again without the
  // password, but it can tell the user there is unfinished setup waiting.
})
</script>

<template>
  <div class="card two-step-card">
    <h3>两步验证</h3>

    <div v-if="status?.enrolled && !pending" class="two-step-status">
      <p class="muted">
        已开启{{ status.confirmed_at ? `（开启时间：${fmtTime(status.confirmed_at)}）` : '' }}。
      </p>
      <p class="muted">
        剩余备用恢复码：<strong>{{ status.recovery_remaining }}</strong>
        <template v-if="status.recovery_generated_at">（生成时间：{{
          fmtTime(status.recovery_generated_at)
        }}）</template>
      </p>
      <p v-if="status.recovery_remaining <= 2" class="warn-line">
        备用恢复码所剩不多——建议在急需之前重新生成一组。
      </p>

      <div class="two-step-actions">
        <button class="btn" type="button" @click="showRegenForm = !showRegenForm">
          重新生成备用恢复码
        </button>
        <button class="btn btn-danger" type="button" @click="showDisableForm = !showDisableForm">
          关闭两步验证
        </button>
      </div>

      <form v-if="showRegenForm" class="reauth-form" @submit.prevent="submitRegen">
        <label
          >当前密码
          <input class="input" type="password" autocomplete="current-password" required v-model="regenForm.password" />
        </label>
        <label
          >身份验证器验证码或备用恢复码
          <input class="input" type="text" autocomplete="one-time-code" required v-model="regenForm.code" />
        </label>
        <button class="btn btn-primary" type="submit" :disabled="busy">生成新恢复码</button>
      </form>

      <form v-if="showDisableForm" class="reauth-form" @submit.prevent="submitDisable">
        <label
          >当前密码
          <input class="input" type="password" autocomplete="current-password" required v-model="disableForm.password" />
        </label>
        <label
          >身份验证器验证码或备用恢复码
          <input class="input" type="text" autocomplete="one-time-code" required v-model="disableForm.code" />
        </label>
        <button class="btn btn-danger" type="submit" :disabled="busy">确认关闭</button>
      </form>
    </div>

    <div v-else-if="!pending" class="two-step-enrol">
      <p class="muted">
        开启后，登录时除密码外还需输入身份验证器应用生成的动态码（或备用恢复码）。请输入当前密码开始设置。
      </p>
      <p v-if="status?.pending" class="muted">
        设置尚未完成<template v-if="minutesLeft">，还剩 {{ minutesLeft }} 分钟过期</template>。请输入当前密码以继续。
      </p>
      <form class="reauth-form" @submit.prevent="startEnrolment(false)">
        <label
          >当前密码
          <input class="input" type="password" autocomplete="current-password" required v-model="startPassword" />
        </label>
        <div class="two-step-actions" v-if="status?.pending">
          <button class="btn btn-primary" type="submit" :disabled="busy">重新显示二维码</button>
          <button class="btn" type="button" :disabled="busy" @click="startEnrolment(true)">重新开始</button>
        </div>
        <button v-else class="btn btn-primary" type="submit" :disabled="busy">
          开启两步验证
        </button>
      </form>
    </div>

    <div v-else class="two-step-enrol">
      <p v-if="minutesLeft" class="muted">请在 {{ minutesLeft }} 分钟内完成两步验证设置。</p>

      <div class="enrol-grid">
        <div class="enrol-qr">
          <img v-if="qrSrc" :src="qrSrc" alt="两步验证设置二维码" />
          <p v-else class="muted">
            二维码生成失败，请在验证器应用中手动输入下方密钥，或刷新页面重试。
          </p>
        </div>
        <div class="enrol-manual">
          <p class="muted">无法扫描二维码？请在身份验证器应用中手动输入以下密钥：</p>
          <div class="secret-groups" @click="copySecret">{{ pending.secret_groups }}</div>
          <button class="btn btn-sm" type="button" @click="copySecret">复制</button>
          <p class="muted manual-line">
            手动添加身份验证器时请使用以下参数：<br>
            账号：{{ pending.manual.account }}<br>
            签发方：{{ pending.manual.issuer }}<br>
            类型：基于时间 (TOTP)<br>
            位数：{{ pending.manual.digits }} 位<br>
            周期：{{ pending.manual.period }} 秒<br>
            算法：{{ pending.manual.algorithm }}<br>
          </p>
        </div>
      </div>

      <form class="reauth-form" @submit.prevent="confirmEnrolment">
        <label>
          输入身份验证器应用生成的验证码
          <input
            class="input"
            type="text"
            autocomplete="one-time-code"
            required
            v-model="confirmCode"
          />
        </label>
        <button class="btn btn-primary" type="submit" :disabled="busy">确认开启</button>
      </form>
    </div>

    <div v-if="recoveryCodes" class="recovery-reveal">
      <p><strong>请立即妥善保存这些备用恢复码，关闭后将不再显示。</strong></p>
      <p class="muted">当你无法使用身份验证器时，每组恢复码均可用于登录一次。</p>
      <ul class="recovery-list">
        <li v-for="c in recoveryCodes" :key="c" class="mono">{{ c }}</li>
      </ul>
      <button class="btn btn-sm" type="button" @click="recoveryCodes = null">我已保存</button>
    </div>
  </div>
</template>

<style scoped>
.two-step-card {
  max-width: 640px;
}
.two-step-actions {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
}
.reauth-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  max-width: 380px;
  margin-top: var(--sp-3);
}
.reauth-form label {
  font-size: var(--fs-sm);
  color: var(--text-2);
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.warn-line {
  color: var(--warn);
  font-size: var(--fs-sm);
}
.enrol-grid {
  display: flex;
  gap: var(--sp-4);
  flex-wrap: wrap;
  margin-top: var(--sp-3);
  align-items: flex-start;
}
.enrol-qr img {
  width: 240px;
  height: 240px;
  /* The QR needs fixed black-on-white contrast for scanners in every theme,
     so it gets an explicit light backdrop regardless of the app's own theme. */
  background: #fff;
  padding: var(--sp-2);
  border-radius: var(--radius);
}
.enrol-manual {
  flex: 1;
  min-width: 220px;
}
.secret-groups {
  font-family: ui-monospace, monospace;
  font-size: var(--fs-lg);
  user-select: all;
  background: var(--bg-sunken);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: var(--sp-2) var(--sp-3);
  margin: var(--sp-2) 0;
  cursor: text;
  word-break: break-all;
}
.manual-line {
  margin-top: var(--sp-2);
}
.recovery-reveal {
  margin-top: var(--sp-3);
  background: var(--bg-sunken);
  border: 1px solid var(--action);
  border-radius: var(--radius);
  padding: var(--sp-3);
}
.recovery-list {
  font-family: ui-monospace, monospace;
  columns: 2;
  margin: var(--sp-2) 0;
  padding-left: var(--sp-4);
}
</style>
