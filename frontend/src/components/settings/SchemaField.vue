<script setup lang="ts">
// One config field row: label (schema title, else humanized key, + dotted key)
// beside a control
// chosen from the field's classified kind. Ports settings.js::renderField. The
// control model is a string (inputs/selects/textarea) or boolean (checkbox);
// the parent owns the value and dirty tracking, this component is presentational
// plus the env-override chip, field description, and inline 422 error slot.
import { computed } from 'vue'
import { humanize, envVarName, type FieldDescriptor, type ControlValue } from '../../utils/schema'
import type { MaskedSecret } from '../../api/types'

const props = defineProps<{
  field: FieldDescriptor
  modelValue: ControlValue
  /** The raw config value from GET /api/config (masked marker for secrets). */
  rawValue: unknown
  envOverride: boolean
  error: string | null
}>()

const emit = defineEmits<{ (e: 'update:modelValue', v: ControlValue): void }>()

const ENUM_LABELS: Record<string, string> = {
  personal: '个人空间',
  shared: '共享空间',
  sqlite: 'SQLite（内置单文件）',
  postgres: 'PostgreSQL',
  auto: '自动检测（优先 GPU）',
  cpu: '仅 CPU',
  cuda: 'NVIDIA CUDA (GPU)',
  chinese_whispers: 'Chinese Whispers（图传播聚类）',
  hdbscan: 'HDBSCAN（密度聚类）',
  assign: '归属认领',
  low_confidence: '低置信度复核',
  reassign: '改判人物',
  merge: '合并未命名分组',
  merge_named: '合并已命名人物',
  new_person: '发现新人物',
}

const FIELD_TITLE_FALLBACKS: Record<string, string> = {
  'nas.url': '群晖 API 地址',
  'nas.web_url': '群晖照片网页地址',
  'nas.verify_tls': '验证 TLS 证书',
  'nas.account': '群晖账号',
  'nas.password': '群晖密码',
  'nas.otp_code': '一次性验证码 (OTP)',
  'nas.device_name': '设备名称',
  'nas.spaces': '同步空间',
  'nas.requests_per_second': '每秒读取请求数',
  'nas.write_requests_per_second': '每秒写入请求数',
  'nas.timeout_s': '请求超时（秒）',
  'storage.data_dir': '数据目录',
  'storage.models_dir': '模型目录',
  'storage.keep_originals': '保留原图缓存',
  'storage.originals_cache_gb': '原图缓存上限 (GB)',
}

function optionLabel(opt: unknown): string {
  const s = String(opt)
  return ENUM_LABELS[s] ?? s
}

const name = computed(() => {
  if (props.field.title && /[\u4e00-\u9fff]/.test(props.field.title)) return props.field.title
  return FIELD_TITLE_FALLBACKS[props.field.dotted] || props.field.title || humanize(props.field.key)
})
const kind = computed(() => props.field.info.kind)

// String/select/textarea/number all bind a string model; checkbox binds bool.
const strValue = computed<string>({
  get: () => String(props.modelValue ?? ''),
  set: (v) => emit('update:modelValue', v),
})
const boolValue = computed<boolean>({
  get: () => !!props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

// An array of enum values renders as one checkbox per option, still bound to the
// comma-joined string model every array control uses.
const checked = computed(() => new Set(strValue.value.split(',').map((s) => s.trim())))
function toggle(opt: unknown, on: boolean) {
  const next = (props.field.info.itemEnum || []).filter((o) =>
    o === opt ? on : checked.value.has(String(o)),
  )
  emit('update:modelValue', next.join(', '))
}

const secretPlaceholder = computed(() => {
  const raw = props.rawValue as MaskedSecret | undefined
  return raw && raw.set ? '已设置——留空以保持不变' : '未设置'
})

const envMessage = computed(
  () =>
    `已被环境变量 ${envVarName(props.field.section, props.field.key)} 覆盖——在此保存的值不会生效`,
)
</script>

<template>
  <div class="field-row" :class="{ 'has-error': !!error }">
    <div class="field-label">
      <span class="field-name">{{ name }}</span>
      <span class="field-key">{{ field.dotted }}</span>
    </div>
    <div class="field-control">
      <input
        v-if="kind === 'password'"
        class="input"
        type="password"
        autocomplete="new-password"
        :placeholder="secretPlaceholder"
        v-model="strValue"
      />
      <select v-else-if="kind === 'enum'" class="select" v-model="strValue">
        <option v-for="opt in field.info.options" :key="String(opt)" :value="String(opt)">
          {{ optionLabel(opt) }}
        </option>
      </select>
      <input v-else-if="kind === 'boolean'" class="check" type="checkbox" v-model="boolValue" />
      <div v-else-if="kind === 'array' && field.info.itemEnum" class="checks">
        <label v-for="opt in field.info.itemEnum" :key="String(opt)" class="check-option">
          <input
            class="check"
            type="checkbox"
            :checked="checked.has(String(opt))"
            @change="toggle(opt, ($event.target as HTMLInputElement).checked)"
          />
          {{ optionLabel(opt) }}
        </label>
      </div>
      <input
        v-else-if="kind === 'array'"
        class="input"
        type="text"
        placeholder="以英文逗号分隔"
        v-model="strValue"
      />
      <textarea v-else-if="kind === 'object'" v-model="strValue"></textarea>
      <input
        v-else-if="kind === 'integer' || kind === 'number'"
        class="input"
        type="number"
        :step="kind === 'number' ? 'any' : undefined"
        v-model="strValue"
      />
      <input v-else class="input" type="text" v-model="strValue" />

      <div v-if="field.description" class="field-desc">{{ field.description }}</div>
      <details v-if="field.details" class="field-details">
        <summary>技术细节</summary>
        <div class="field-details-body">{{ field.details }}</div>
      </details>
      <span v-if="envOverride" class="env-chip">{{ envMessage }}</span>
      <div v-if="error" class="field-error">{{ error }}</div>
    </div>
  </div>
</template>

<style scoped>
.field-row {
  display: grid;
  grid-template-columns: 240px 1fr;
  gap: var(--sp-4);
  align-items: start;
  padding: var(--sp-3) 0;
  border-bottom: 1px solid var(--border-soft);
}
.field-label .field-name {
  font-weight: 500;
}
.field-label .field-key {
  display: block;
  margin-top: 2px;
  font-size: var(--fs-sm);
  color: var(--text-3);
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
}
.field-control {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  min-width: 0;
}
.field-control .input,
.field-control .select,
.field-control textarea {
  max-width: 420px;
  width: 100%;
}
.field-control textarea {
  font: inherit;
  font-family: ui-monospace, monospace;
  padding: var(--sp-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--bg-raised);
  color: var(--text);
  min-height: 4.5em;
}
.field-control .check {
  margin: 4px 0 0;
}
.checks {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1) var(--sp-4);
}
.check-option {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  font-family: ui-monospace, 'SF Mono', Menlo, monospace;
}
.check-option .check {
  margin: 0;
}
.field-desc {
  font-size: var(--fs-sm);
  color: var(--text-2);
  white-space: pre-wrap;
}
.field-details {
  font-size: var(--fs-sm);
  color: var(--text-3);
  max-width: 68ch;
}
.field-details > summary {
  cursor: pointer;
  width: fit-content;
  list-style: none;
  color: var(--text-3);
  opacity: 0.85;
}
.field-details > summary::-webkit-details-marker {
  display: none;
}
.field-details > summary::before {
  content: '▸ ';
}
.field-details[open] > summary::before {
  content: '▾ ';
}
.field-details > summary:hover {
  color: var(--text-2);
}
.field-details-body {
  margin-top: var(--sp-1);
  padding-left: 0.9em;
  border-left: 1px solid var(--border-soft);
  white-space: pre-wrap;
}
.field-error {
  font-size: var(--fs-sm);
  color: var(--danger);
}
.env-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  align-self: flex-start;
  font-size: var(--fs-sm);
  background: rgba(224, 133, 15, 0.16);
  color: var(--warn);
  border-radius: 999px;
  padding: 2px 8px;
}
.field-row.has-error .input,
.field-row.has-error .select,
.field-row.has-error textarea {
  border-color: var(--danger);
}
</style>
