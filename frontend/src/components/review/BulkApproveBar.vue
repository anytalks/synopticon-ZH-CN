<script setup lang="ts">
// Bulk-approve control (the toolbar's `.bulk` cluster): approve every pending
// item of the current kind at/above a minimum confidence, or approve all pending
// items (for the current kind or across all kinds) via one-click review-all.
import { ref, computed } from 'vue'
import { confirm } from '../../composables/useConfirm'

const props = defineProps<{
  kind: string
  pendingByKind: Record<string, number>
}>()

const emit = defineEmits<{
  (e: 'approve', payload: { kind: string; minConfidence: number }): void
  (e: 'approve-all', payload: { kind: string }): void
}>()

const minConf = ref(0.55)

const KIND_LABELS: Record<string, string> = {
  assign: '归属认领',
  low_confidence: '低置信度复核',
  reassign: '改判人物',
  merge: '合并未命名分组',
  merge_named: '合并已命名人物',
  new_person: '发现新人物',
}

const effectiveKind = computed(() => props.kind || 'assign')
const effectiveKindLabel = computed(() => KIND_LABELS[effectiveKind.value] ?? effectiveKind.value)

const targetAllCount = computed(() => {
  if (props.kind) return props.pendingByKind[props.kind] ?? 0
  return Object.values(props.pendingByKind).reduce((sum, n) => sum + n, 0)
})

const approveAllLabel = computed(() => {
  const base = props.kind ? '一键全审当前类' : '一键全审'
  return targetAllCount.value > 0 ? `${base} (${targetAllCount.value})` : base
})

async function submit(): Promise<void> {
  const ok = await confirm({
    title: '批量通过',
    message: `确定批量通过所有待审核的「${effectiveKindLabel.value}」建议（置信度 ≥ ${minConf.value}）吗？`,
    okLabel: '确认通过',
    danger: false,
  })
  if (!ok) return
  emit('approve', { kind: effectiveKind.value, minConfidence: minConf.value })
}

async function submitAll(): Promise<void> {
  if (targetAllCount.value <= 0) return

  let message: string
  let isDanger: boolean

  if (!props.kind) {
    const breakdown = Object.entries(props.pendingByKind)
      .filter(([, n]) => n > 0)
      .map(([k, n]) => `• ${KIND_LABELS[k] ?? k}：${n} 条`)
      .join('\n')
    const hasNamedMerge = (props.pendingByKind.merge_named ?? 0) > 0
    const lines = [
      `确定一键通过全部待审核建议（共 ${targetAllCount.value} 条，不限类型与置信度）吗？`,
    ]
    if (breakdown) lines.push(breakdown)
    if (hasNamedMerge) {
      lines.push('注意：其中包含「合并已命名人物」，请谨慎确认。')
    }
    lines.push('仅在本地标记为“已通过”，尚未写回群晖 NAS。')
    message = lines.join('\n\n')
    isDanger = true
  } else {
    const kindLabel = KIND_LABELS[props.kind] ?? props.kind
    message = `确定一键通过当前类型「${kindLabel}」的全部 ${targetAllCount.value} 条待审核建议吗？（不限置信度，仅在本地标记为“已通过”，尚未写回群晖 NAS。）`
    isDanger = props.kind === 'merge_named' || props.kind === 'merge' || props.kind === 'reassign'
  }

  const ok = await confirm({
    title: props.kind ? '一键全审当前类' : '一键全审全部待审核',
    message,
    okLabel: `确认通过 ${targetAllCount.value} 条`,
    danger: isDanger,
  })
  if (!ok) return
  emit('approve-all', { kind: props.kind })
}
</script>

<template>
  <div class="bulk">
    <input
      v-model.number="minConf"
      class="input input-sm"
      type="number"
      step="0.01"
      aria-label="批量通过的最低置信度"
    />
    <button class="btn btn-sm" type="button" @click="submit">
      批量通过{{ effectiveKindLabel }} &ge; 置信度
    </button>
    <button
      class="btn btn-sm btn-action"
      type="button"
      :disabled="targetAllCount === 0"
      :title="props.kind ? '一键通过当前类型全部待审核建议（不限置信度）' : '一键通过所有待审核建议（不限类型与置信度）'"
      @click="submitAll"
    >
      {{ approveAllLabel }}
    </button>
  </div>
</template>

<style scoped>
.bulk {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  align-items: center;
}
</style>
