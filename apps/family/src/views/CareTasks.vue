<template>
  <div>
    <div class="topbar">
      <h1>{{ isCaregiver ? '今日照护打卡' : '照护动态' }}</h1>
      <p>{{ isCaregiver ? '签到留痕 / 异常上报' : '查看今日照护任务执行情况' }}</p>
    </div>
    <div class="card">
      <div class="task" v-for="t in tasks" :key="t.id">
        <div>
          <div><b>{{ t.elder?.name }}</b> · {{ t.title }}</div>
          <div class="muted" style="font-size: 12px">
            {{ new Date(t.scheduledAt).toLocaleTimeString() }} · {{ t.status }}
          </div>
        </div>
        <button
          v-if="isCaregiver && t.status === 'pending'"
          class="btn"
          style="width: auto; padding: 8px 12px"
          @click="checkin(t)"
        >
          打卡
        </button>
      </div>
      <p v-if="!tasks.length" class="muted">暂无任务</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import http from '../api';

const user = ref(JSON.parse(localStorage.getItem('nh_family_user') || 'null'));
const tasks = ref<any[]>([]);
const isCaregiver = computed(() => user.value?.role === 'caregiver' || user.value?.role === 'nurse' || user.value?.role === 'admin');

async function load() {
  tasks.value = await http.get('/care/tasks');
}

async function checkin(t: any) {
  await http.post(`/care/tasks/${t.id}/checkin`, { note: '移动端打卡' });
  await load();
}

onMounted(load);
</script>
