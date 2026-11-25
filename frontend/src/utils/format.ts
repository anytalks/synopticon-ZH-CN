// Display formatters shared by the stats views. Plain functions over plain
// numbers: every one accepts null and renders an em dash for it.

export function num(n: number | null | undefined): string {
  return n == null ? '—' : n.toLocaleString('zh-CN')
}

/** 0..1 fraction → "5.2%"; one decimal under 10%, whole numbers above. */
export function pct(f: number | null | undefined): string {
  if (f == null || !Number.isFinite(f)) return '—'
  const p = f * 100
  if (p > 0 && p < 0.1) return '<0.1%'
  if (p > 99.5 && p < 100) return Math.min(p, 99.9).toFixed(1) + '%'
  return (p < 10 ? p.toFixed(1) : Math.round(p).toString()) + '%'
}

export function fmtBytes(n: number | null | undefined): string {
  if (n == null) return '—'
  const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']
  let i = 0
  let v = n
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024
    i++
  }
  return (i === 0 ? v : v.toFixed(1)) + ' ' + u[i]
}

/** Seconds → "3天 4小时", "2小时 15分", "4分 10秒", "12秒". Two units at most. */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  let s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s}秒`
  const d = Math.floor(s / 86400)
  s -= d * 86400
  const h = Math.floor(s / 3600)
  s -= h * 3600
  const m = Math.floor(s / 60)
  s -= m * 60
  if (d) return h ? `${d}天 ${h}小时` : `${d}天`
  if (h) return m ? `${h}小时 ${m}分` : `${h}小时`
  return s ? `${m}分 ${s}秒` : `${m}分`
}

export function fmtDate(ts: number | null | undefined): string {
  return ts ? new Date(ts * 1000).toLocaleDateString('zh-CN') : '—'
}

export function fmtMonthOf(ts: number | null | undefined): string {
  return ts
    ? new Date(ts * 1000).toLocaleDateString('zh-CN', { month: 'short', year: 'numeric' })
    : '—'
}

/**
 * Taken-time timestamps are Synology's local wall clock stored as if UTC, so
 * they are rendered in UTC to show the date the photo was actually taken.
 */
export function fmtTakenDate(ts: number | null | undefined): string {
  return ts ? new Date(ts * 1000).toLocaleDateString('zh-CN', { timeZone: 'UTC' }) : '—'
}

/** 'YYYY-MM-DD' → a locale date, without a timezone shift. */
export function fmtDay(day: string | null | undefined): string {
  if (!day) return '—'
  const [y, m, d] = day.split('-').map(Number)
  if (!y || !m || !d) return day
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('zh-CN', { timeZone: 'UTC' })
}

/** 'YYYY-MM' → "2026年3月". */
export function fmtMonth(month: string): string {
  const [y, m] = month.split('-').map(Number)
  if (!y || !m) return month
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString('zh-CN', {
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

/** 12,840 → "1.3万" for axis ticks. */
export function compact(n: number): string {
  return new Intl.NumberFormat('zh-CN', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
}
