<script setup lang="ts">
// Change the signed-in user's password. POST /api/auth/change-password does the
// old-password check server-side; the confirm field is only a typo guard.
import { reactive } from 'vue'
import { postJSON, ApiError } from '../../../api/client'
import { toast } from '../../../stores/toasts'

const pw = reactive({ current: '', next: '', confirm: '' })

function errMsg(err: unknown, fallback: string): string {
  if (err instanceof ApiError) return err.message || fallback
  return (err as Error)?.message || fallback
}

async function changePassword(): Promise<void> {
  if (pw.next !== pw.confirm) {
    toast('两次输入的新密码不一致', 'error')
    return
  }
  try {
    await postJSON('/api/auth/change-password', {
      current_password: pw.current,
      new_password: pw.next,
    })
    pw.current = pw.next = pw.confirm = ''
    toast('密码已更新', 'ok')
  } catch (err) {
    toast(errMsg(err, '无法修改密码'), 'error')
  }
}
</script>

<template>
  <div class="card password-section">
    <h3>修改密码</h3>
    <form class="password-form" @submit.prevent="changePassword">
      <label>
        <span>当前密码</span>
        <input class="input" type="password" autocomplete="current-password" required v-model="pw.current" />
      </label>
      <label>
        <span>新密码</span>
        <input class="input" type="password" autocomplete="new-password" required v-model="pw.next" />
      </label>
      <label>
        <span>确认新密码</span>
        <input class="input" type="password" autocomplete="new-password" required v-model="pw.confirm" />
      </label>
      <button class="btn btn-primary" type="submit">更新密码</button>
    </form>
  </div>
</template>

<style scoped>
.password-section {
  max-width: 640px;
}
.password-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  max-width: 380px;
  margin-top: var(--sp-3);
}
.password-form label {
  font-size: var(--fs-sm);
  color: var(--text-2);
}
.password-form label span {
  margin-right: var(--sp-3);
}
</style>
