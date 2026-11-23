<template>
  <div class="page-card">
    <h2 class="page-title">收费财务</h2>
    <div class="toolbar">
      <el-button type="primary" @click="generate">生成本月账单</el-button>
      <el-button @click="load">刷新</el-button>
      <el-tag type="info">在线支付（微信/支付宝/云闪付）接口已预留，当前为线下登记</el-tag>
    </div>
    <el-table :data="bills" stripe>
      <el-table-column label="老人">
        <template #default="{ row }">{{ row.elder?.name }}</template>
      </el-table-column>
      <el-table-column label="账期">
        <template #default="{ row }">
          {{ new Date(row.periodStart).toLocaleDateString() }} ~
          {{ new Date(row.periodEnd).toLocaleDateString() }}
        </template>
      </el-table-column>
      <el-table-column prop="totalAmount" label="应付" />
      <el-table-column prop="paidAmount" label="已付" />
      <el-table-column prop="status" label="状态" />
      <el-table-column label="明细">
        <template #default="{ row }">
          {{ row.lines?.map((l: any) => `${l.feeName}¥${l.amount}`).join(' / ') }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button size="small" type="primary" :disabled="row.status === 'paid'" @click="pay(row)">登记缴费</el-button>
          <el-button size="small" disabled>去支付</el-button>
        </template>
      </el-table-column>
    </el-table>

    <h3 style="margin-top: 24px">收费项目</h3>
    <el-table :data="feeItems" size="small">
      <el-table-column prop="code" label="编码" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="defaultPrice" label="默认价" />
      <el-table-column prop="unit" label="单位" />
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import http from '../api/http';

const bills = ref<any[]>([]);
const feeItems = ref<any[]>([]);

async function load() {
  bills.value = await http.get('/billing/bills');
  feeItems.value = await http.get('/billing/fee-items');
}

async function generate() {
  const res: any = await http.post('/billing/bills/generate', {});
  ElMessage.success(`生成 ${res.count} 张账单`);
  load();
}

async function pay(row: any) {
  const remain = row.totalAmount - row.paidAmount;
  const { value } = await ElMessageBox.prompt(`待收 ¥${remain}，输入本次收款金额`, '登记缴费', {
    inputValue: String(remain),
  });
  await http.post(`/billing/bills/${row.id}/pay`, { amount: Number(value), method: 'cash' });
  ElMessage.success('缴费成功');
  load();
}

onMounted(load);
</script>
