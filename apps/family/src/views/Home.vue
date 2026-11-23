<template>
  <div>
    <div class="topbar">
      <h1>你好，{{ user?.name }}</h1>
      <p>{{ roleText }} · 信息透明可查</p>
    </div>
    <div class="card" v-if="user?.role === 'family'">
      <h3>绑定老人</h3>
      <div v-for="e in me?.elders || []" :key="e.id" class="row">
        <span>{{ e.name }}</span>
        <span class="chip">{{ e.relation || '家属' }}</span>
      </div>
      <p v-if="!(me?.elders?.length)" class="muted">暂无绑定老人</p>
    </div>
    <div class="card">
      <h3>快捷入口</h3>
      <p class="muted">查看账单明细、每日餐食、照护执行情况。支付通道已预留。</p>
      <button class="btn secondary" style="margin-top: 8px" @click="logout">退出登录</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import http from '../api';

const router = useRouter();
const user = ref(JSON.parse(localStorage.getItem('nh_family_user') || 'null'));
const me = ref<any>(null);
const roleText = computed(() =>
  user.value?.role === 'family' ? '家属端' : user.value?.role === 'caregiver' ? '护理端' : '移动端',
);

onMounted(async () => {
  me.value = await http.get('/auth/me');
});

function logout() {
  localStorage.removeItem('nh_family_token');
  localStorage.removeItem('nh_family_user');
  router.push('/login');
}
</script>
