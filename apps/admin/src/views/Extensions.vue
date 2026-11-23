<template>
  <div class="page-card">
    <h2 class="page-title">扩展注册中心</h2>
    <p class="hint">预留新接口扩展点：注册后出现在全局搜索，后续可挂载真实模块。</p>

    <el-row :gutter="16">
      <el-col :md="12" :xs="24">
        <h3>注册新扩展</h3>
        <el-form label-width="90px">
          <el-form-item label="ID"><el-input v-model="form.id" placeholder="ext_custom_xxx" /></el-form-item>
          <el-form-item label="标题"><el-input v-model="form.title" /></el-form-item>
          <el-form-item label="分组">
            <el-select v-model="form.group" style="width:100%">
              <el-option v-for="(label, key) in groups" :key="key" :label="label" :value="key" />
            </el-select>
          </el-form-item>
          <el-form-item label="路径"><el-input v-model="form.path" placeholder="/ext/demo" /></el-form-item>
          <el-form-item label="API前缀"><el-input v-model="form.apiPrefix" placeholder="/api/ext/demo" /></el-form-item>
          <el-form-item label="关键词"><el-input v-model="form.keywordsText" placeholder="逗号分隔" /></el-form-item>
          <el-form-item label="说明"><el-input v-model="form.description" type="textarea" /></el-form-item>
          <el-button type="primary" @click="register">注册扩展</el-button>
        </el-form>
      </el-col>
      <el-col :md="12" :xs="24">
        <h3>扩展点</h3>
        <el-table :data="catalog?.extensionPoints || []" size="small">
          <el-table-column prop="id" label="扩展点" />
          <el-table-column prop="desc" label="说明" />
        </el-table>
        <h3 style="margin-top:16px">已注册动态模块</h3>
        <el-table :data="dynamic" size="small">
          <el-table-column prop="title" label="标题" />
          <el-table-column prop="apiPrefix" label="API" />
          <el-table-column prop="path" label="路径" />
        </el-table>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { MODULE_GROUP_LABELS } from '@nh/shared';
import http from '../api/http';

const groups = MODULE_GROUP_LABELS;
const catalog = ref<any>(null);
const dynamic = ref<any[]>([]);
const form = reactive({
  id: '',
  title: '',
  group: 'system',
  path: '',
  apiPrefix: '',
  keywordsText: '',
  description: '',
});

async function load() {
  catalog.value = await http.get('/extensions/catalog');
  dynamic.value = await http.get('/extensions/dynamic');
}
async function register() {
  await http.post('/extensions/register', {
    ...form,
    keywords: form.keywordsText.split(/[,，\s]+/).filter(Boolean),
  });
  ElMessage.success('已注册，可在顶部搜索中命中');
  form.id = form.title = form.path = form.apiPrefix = form.keywordsText = form.description = '';
  load();
}
onMounted(load);
</script>

<style scoped>
.hint { color: #6a7b71; margin-top: -8px; }
</style>
