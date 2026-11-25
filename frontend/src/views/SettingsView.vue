<script setup lang="ts">
// Settings page: a single tab bar over the config sections plus an Access tab.
// Ports settings.html.j2's tabs layout. The config tabs are driven by SchemaForm
// (schema-driven form + save bar + dirty guard); the Access tab hosts the
// password / API-key forms. A section tab shows an error dot when SchemaForm
// reports a 422 field error in it. SchemaForm stays mounted across tab switches
// so its dirty state (and the unsaved-changes guard) survives navigation within
// the page.
import { ref } from 'vue'
import SchemaForm from '../components/settings/SchemaForm.vue'
import AccessTab from '../components/settings/AccessTab.vue'
import ModelsTab from '../components/settings/ModelsTab.vue'
import { SECTIONS, LABELS } from '../utils/schema'

const TABS: string[] = [...SECTIONS, 'models', 'access']
const TAB_LABELS: Record<string, string> = {
  nas: '群晖连接',
  storage: '存储与缓存',
  database: '数据库',
  inference: '推理与加速',
  detection: '人脸检测',
  restoration: '画质修复',
  clustering: '聚类分组',
  crossref: '比对与建议',
  security: '安全设置',
  mcp: 'MCP 接口',
  models: '模型管理',
  access: '账号与权限',
}
const activeTab = ref<string>(SECTIONS[0])
const errorSections = ref<string[]>([])

function activate(tab: string): void {
  activeTab.value = tab
}
</script>

<template>
  <div class="page">
    <div class="settings-tabs" role="tablist" aria-label="设置分组">
      <button
        v-for="tab in TABS"
        :key="tab"
        class="settings-tab"
        type="button"
        role="tab"
        :class="{ active: activeTab === tab, 'has-error': errorSections.includes(tab) }"
        :aria-selected="activeTab === tab ? 'true' : 'false'"
        @click="activate(tab)"
      >
        {{ TAB_LABELS[tab] || LABELS[tab] || tab }}
        <span class="err-dot" aria-hidden="true"></span>
      </button>
    </div>

    <SchemaForm
      v-show="activeTab !== 'access' && activeTab !== 'models'"
      :active-section="activeTab"
      @update:error-sections="errorSections = $event"
      @activate="activate"
    />
    <ModelsTab v-if="activeTab === 'models'" />
    <AccessTab v-show="activeTab === 'access'" />
  </div>
</template>

<style scoped>
.settings-tabs {
  display: flex;
  gap: var(--sp-1);
  flex-wrap: wrap;
  border-bottom: 1px solid var(--border-soft);
  margin-bottom: var(--sp-4);
}
.settings-tab {
  position: relative;
  background: transparent;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-2);
  padding: var(--sp-2) var(--sp-3);
  cursor: pointer;
  font: inherit;
}
.settings-tab:hover {
  color: var(--text);
}
.settings-tab.active {
  color: var(--action);
  border-bottom-color: var(--action);
  font-weight: 600;
}
.settings-tab .err-dot {
  display: none;
  position: absolute;
  top: 5px;
  right: 0;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--danger);
}
.settings-tab.has-error .err-dot {
  display: block;
}
</style>
