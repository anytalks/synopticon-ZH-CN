// Translates web_auth_log's protocol identifiers -- event, outcome, reason --
// into the plain-language labels CLAUDE.md's translation rule requires: none
// of the three may reach the DOM raw. Mirrors jobs.ts's jobLabel(): an unknown
// value falls back to itself rather than disappearing, so a reason added on
// the backend before this map catches up still renders as *something*.

const EVENT_LABELS: Record<string, string> = {
  login: '密码登录',
  login_code: '两步验证码',
  logout: '退出登录',
  create_account: '创建账号',
  password_change: '修改密码',
  security_change: '修改安全设置',
  api_key: 'API 密钥',
  mcp_token: 'MCP 令牌',
}

const OUTCOME_LABELS: Record<string, string> = {
  success: '成功',
  failure: '失败',
  blocked: '已拦截',
  pending: '等待验证',
}

const REASON_LABELS: Record<string, string> = {
  rate_limited: '触发登录限流',
  password_ok: '密码正确 — 需输入验证码',
  password_bad: '密码错误 — 需输入验证码',
  bad_credentials: '用户名或密码错误',
  missing_credentials: '未填写用户名或密码',
  unknown_challenge: '登录验证会话已过期',
  bad_code: '两步验证码错误',
  bad_password: '密码错误',
  totp_enrolled: '已开启两步验证',
  totp_disabled: '已关闭两步验证',
  recovery_codes_regenerated: '已重新生成备用恢复码',
  session_pin_changed: '已更改会话绑定设置',
  reauth_failed: '密码或验证码未通过校验',
  unknown_or_revoked_key: 'API 密钥无效或已吊销',
  unknown_or_revoked_token: 'MCP 令牌无效或已吊销',
  missing_token: '未提供 MCP 令牌',
}

export function eventLabel(event: string | null | undefined): string {
  if (!event) return ''
  return EVENT_LABELS[event] ?? event
}

export function outcomeLabel(outcome: string | null | undefined): string {
  if (!outcome) return ''
  return OUTCOME_LABELS[outcome] ?? outcome
}

export function reasonLabel(reason: string | null | undefined): string {
  if (!reason) return ''
  return REASON_LABELS[reason] ?? reason
}
