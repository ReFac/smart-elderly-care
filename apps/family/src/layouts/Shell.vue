<template>
  <div class="app-shell">
    <router-view />
    <nav class="tabbar">
      <router-link to="/home" :class="{ active: route.path === '/home' }">首页</router-link>
      <router-link to="/bills" :class="{ active: route.path === '/bills' }">账单</router-link>
      <router-link to="/meals" :class="{ active: route.path === '/meals' }">餐食</router-link>
      <router-link to="/care" :class="{ active: route.path === '/care' }">照护</router-link>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router';
const route = useRoute();
</script>
