<template>
  <div class="page-card">
    <h2 class="page-title">后勤物资</h2>
    <el-tabs v-model="tab">
      <el-tab-pane label="库存" name="stock">
        <div class="toolbar">
          <el-input v-model="form.name" placeholder="物资名称" style="width: 140px" />
          <el-select v-model="form.category" style="width: 120px">
            <el-option label="耗材" value="consumable" />
            <el-option label="护理用品" value="care" />
            <el-option label="纸尿裤" value="diaper" />
            <el-option label="其他" value="other" />
          </el-select>
          <el-input-number v-model="form.quantity" :min="0" />
          <el-button type="primary" @click="create">新增</el-button>
          <el-button type="warning" @click="loadLow">低库存预警</el-button>
        </div>
        <el-alert v-if="low.length" type="warning" :closable="false" style="margin-bottom:12px"
          :title="`低库存 ${low.length} 项：${low.map((i:any)=>i.name).join('、')}`" />
        <el-table :data="items" stripe size="small">
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="category" label="分类" />
          <el-table-column prop="quantity" label="库存" />
          <el-table-column prop="lowStock" label="预警线" />
          <el-table-column prop="unit" label="单位" />
          <el-table-column label="操作" width="220">
            <template #default="{ row }">
              <el-button size="small" @click="stock(row,'in')">入库</el-button>
              <el-button size="small" @click="stock(row,'out')">出库</el-button>
              <el-button size="small" type="danger" @click="remove(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
      <el-tab-pane label="报修工单" name="maint">
        <div class="toolbar">
          <el-input v-model="maint.title" placeholder="报修标题" style="width: 180px" />
          <el-input v-model="maint.location" placeholder="位置" style="width: 140px" />
          <el-button type="primary" @click="createMaint">提交报修</el-button>
        </div>
        <el-table :data="maintenance" size="small">
          <el-table-column prop="title" label="标题" />
          <el-table-column prop="location" label="位置" />
          <el-table-column prop="status" label="状态" />
          <el-table-column label="操作">
            <template #default="{ row }">
              <el-button size="small" :disabled="row.status==='done'" @click="doneMaint(row)">完成</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import http from '../api/http';

const tab = ref('stock');
const items = ref<any[]>([]);
const low = ref<any[]>([]);
const maintenance = ref<any[]>([]);
const form = reactive<any>({ name: '', category: 'consumable', quantity: 20, unit: '件', lowStock: 10 });
const maint = reactive<any>({ title: '', location: '' });

async function load() {
  items.value = await http.get('/inventory/items');
  maintenance.value = await http.get('/inventory/maintenance');
}
async function loadLow() {
  low.value = await http.get('/inventory/items/low-stock');
}
async function create() {
  await http.post('/inventory/items', form);
  ElMessage.success('已新增');
  load();
}
async function stock(row: any, type: string) {
  const { value } = await ElMessageBox.prompt('数量', type === 'in' ? '入库' : '出库', { inputValue: '1' });
  await http.post(`/inventory/items/${row.id}/stock`, { type, quantity: Number(value) });
  load();
}
async function remove(row: any) {
  await http.delete(`/inventory/items/${row.id}`);
  load();
}
async function createMaint() {
  await http.post('/inventory/maintenance', maint);
  maintenance.value = await http.get('/inventory/maintenance');
}
async function doneMaint(row: any) {
  await http.patch(`/inventory/maintenance/${row.id}`, { status: 'done' });
  maintenance.value = await http.get('/inventory/maintenance');
}
onMounted(load);
</script>
