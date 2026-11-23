<template>
  <div class="page-card">
    <h2 class="page-title">系统设置</h2>
    <h3>功能开关</h3>
    <el-table :data="flags" size="small" style="max-width: 560px; margin-bottom: 24px">
      <el-table-column prop="key" label="功能" />
      <el-table-column label="启用">
        <template #default="{ row }">
          <el-switch v-model="row.enabled" @change="(v: boolean) => toggle(row.key, v)" />
        </template>
      </el-table-column>
    </el-table>

    <h3>LLM / OCR（OpenAI 兼容）</h3>
    <el-form label-width="120px" style="max-width: 640px">
      <el-form-item label="Base URL">
        <el-input v-model="ai.baseUrl" placeholder="https://api.deepseek.com/v1" />
      </el-form-item>
      <el-form-item label="API Key">
        <el-input v-model="ai.apiKey" type="password" show-password placeholder="填写后覆盖保存" />
      </el-form-item>
      <el-form-item label="Model">
        <el-input v-model="ai.model" placeholder="deepseek-chat / moonshot-v1 / doubao-*" />
      </el-form-item>
      <el-form-item label="OCR 供应商">
        <el-select v-model="ai.ocrProvider">
          <el-option label="Mock（演示）" value="mock" />
          <el-option label="本地 PaddleOCR（预留）" value="paddle" />
          <el-option label="云端（预留）" value="cloud" />
        </el-select>
      </el-form-item>
      <el-button type="primary" @click="saveAi">保存 AI 配置</el-button>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import http from '../api/http';

const flags = ref<any[]>([]);
const ai = reactive({
  baseUrl: '',
  apiKey: '',
  model: '',
  ocrProvider: 'mock',
  provider: 'openai_compatible',
});

async function load() {
  flags.value = await http.get('/settings/flags');
  const cfg: any = await http.get('/settings/ai');
  if (cfg) {
    ai.baseUrl = cfg.baseUrl;
    ai.model = cfg.model;
    ai.ocrProvider = cfg.ocrProvider;
    ai.apiKey = '';
  }
}

async function toggle(key: string, enabled: boolean) {
  await http.patch('/settings/flags', { key, enabled });
  ElMessage.success('已更新');
}

async function saveAi() {
  const payload: any = { ...ai };
  if (!payload.apiKey) delete payload.apiKey;
  await http.post('/settings/ai', payload);
  ElMessage.success('AI 配置已保存');
  load();
}

onMounted(load);
</script>
