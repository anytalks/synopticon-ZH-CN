// Friendly names for the job ids the API speaks. The ids themselves are the
// CLI command names and stay stable — this is the presentation layer only, so
// the UI never shows a homelabber "extract" or "cluster".
const JOB_LABELS: Record<string, string> = {
  sync: '同步图库',
  extract: '人脸检测与提取',
  cluster: '人脸聚类分组',
  recluster: '重新聚类分组',
  report: '生成审核报告',
  'regen-crops': '重新生成人脸头像',
  benchmark: '性能基准测试',
  'models-download': '下载模型',
  apply: '写回修正到群晖',
  dedupe: '重复照片去重',
  reset: '重置数据',
  'clear-queue': '清空审核队列',
  'clear-applies': '清空待写回队列',
  'prune-queue': '清理失效审核项',
  'delete-crops': '删除人脸头像缓存',
}

export function jobLabel(name: string | null | undefined): string {
  if (!name) return ''
  return JOB_LABELS[name] ?? name
}

// The run ledger records every CLI invocation, including commands the GUI can
// never start, and names `models download` by its group alone.
const COMMAND_LABELS: Record<string, string> = {
  models: JOB_LABELS['models-download'],
  check: '连接检测',
  hwinfo: '硬件信息',
  review: '审核服务（旧版）',
  'apply-all': '全部写回群晖',
  eval: '效果评估',
  'reset-password': '重置密码',
  'web-access': 'Web 访问控制',
  'disable-2fa': '关闭两步验证',
  'session-pin': '会话绑定',
}

/** Label for a raw CLI command name, as the run ledger stores it. */
export function commandLabel(name: string | null | undefined): string {
  if (!name) return ''
  return COMMAND_LABELS[name] ?? jobLabel(name)
}
