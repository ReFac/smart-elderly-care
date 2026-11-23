<template>
  <div class="page-card">
    <h2 class="page-title">楼层与床位</h2>
    <div class="toolbar">
      <el-select v-model="buildingId" placeholder="建筑" style="width: 180px" @change="onBuilding">
        <el-option v-for="b in buildings" :key="b.id" :label="b.name" :value="b.id" />
      </el-select>
      <el-select v-model="floorId" placeholder="楼层" style="width: 140px" @change="loadFloor">
        <el-option v-for="f in floors" :key="f.id" :label="f.name" :value="f.id" />
      </el-select>
      <el-tag>平面图上传字段已预留</el-tag>
    </div>
    <div v-if="floor" class="bed-grid">
      <div
        v-for="bed in flatBeds"
        :key="bed.id"
        class="bed-cell"
        :class="bed.status"
      >
        <div><b>{{ bed.code }}</b></div>
        <div>{{ statusLabel(bed.status) }}</div>
        <div v-if="bed.elder">{{ bed.elder.name }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import http from '../api/http';
import { BED_STATUS_LABELS } from '@nh/shared';

const buildings = ref<any[]>([]);
const buildingId = ref('');
const floorId = ref('');
const floor = ref<any>(null);

const floors = computed(() => buildings.value.find((b) => b.id === buildingId.value)?.floors || []);
const flatBeds = computed(() => {
  if (!floor.value) return [];
  return floor.value.rooms.flatMap((r: any) => r.beds);
});

function statusLabel(s: string) {
  return (BED_STATUS_LABELS as any)[s] || s;
}

function onBuilding() {
  floorId.value = floors.value[0]?.id || '';
  loadFloor();
}

async function loadFloor() {
  if (!floorId.value) return;
  floor.value = await http.get(`/org/floors/${floorId.value}`);
}

onMounted(async () => {
  buildings.value = await http.get('/org/buildings');
  buildingId.value = buildings.value[0]?.id || '';
  onBuilding();
});
</script>
