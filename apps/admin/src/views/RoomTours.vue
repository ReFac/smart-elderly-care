<template>
  <div class="page-card">
    <h2 class="page-title">3D 房态导览</h2>
    <p class="hint">支持全景 / 简易 3D 场景元数据与热点；用户端公开接口 `/api/tours/public`。</p>
    <div class="toolbar">
      <el-input v-model="form.title" placeholder="导览标题" style="width:160px" />
      <el-select v-model="form.sceneType" style="width:120px">
        <el-option label="全景 panorama" value="panorama" />
        <el-option label="3D 模型" value="model3d" />
        <el-option label="平面热点" value="floorplan" />
      </el-select>
      <el-input v-model="form.sceneUrl" placeholder="场景/全景 URL" style="width:220px" />
      <el-input v-model="form.modelUrl" placeholder="glTF/模型 URL（可选）" style="width:200px" />
      <el-switch v-model="form.published" active-text="发布" />
      <el-button type="primary" @click="create">创建</el-button>
    </div>
    <el-table :data="list" stripe>
      <el-table-column prop="title" label="标题" />
      <el-table-column prop="sceneType" label="类型" width="100" />
      <el-table-column label="发布" width="80">
        <template #default="{ row }">{{ row.published ? '是' : '否' }}</template>
      </el-table-column>
      <el-table-column label="热点" width="80">
        <template #default="{ row }">{{ row.hotspots?.length || 0 }}</template>
      </el-table-column>
      <el-table-column label="操作" width="280">
        <template #default="{ row }">
          <el-button size="small" @click="preview(row)">预览</el-button>
          <el-button size="small" @click="addHotspot(row)">加热点</el-button>
          <el-button size="small" @click="togglePub(row)">{{ row.published ? '下架' : '发布' }}</el-button>
          <el-button size="small" type="danger" @click="remove(row)">删</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="active" class="tour-stage">
      <h3>{{ active.title }} · 简易 3D/全景舞台</h3>
      <div class="stage" :style="stageStyle" @pointerdown="onDragStart" @pointermove="onDrag" @pointerup="dragging=false">
        <div class="hotspot" v-for="h in active.hotspots" :key="h.id" :style="hotspotStyle(h)">
          {{ h.label }}
        </div>
        <div class="hint-overlay">拖拽旋转 · yaw {{ yaw.toFixed(0) }}° / pitch {{ pitch.toFixed(0) }}°</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { ElMessage, ElMessageBox } from 'element-plus';
import http from '../api/http';

const list = ref<any[]>([]);
const active = ref<any>(null);
const form = reactive({
  title: '',
  sceneType: 'panorama',
  sceneUrl: 'https://images.unsplash.com/photo-1582719478250-c89cae4dc85b?w=1600',
  modelUrl: '',
  published: true,
  fov: 75,
});
const yaw = ref(0);
const pitch = ref(0);
const dragging = ref(false);
const lastX = ref(0);
const lastY = ref(0);

const stageStyle = computed(() => ({
  backgroundImage: `url(${active.value?.sceneUrl || form.sceneUrl})`,
  backgroundPosition: `${50 + yaw.value / 3}% ${50 + pitch.value / 3}%`,
  transform: `perspective(800px) rotateY(${yaw.value / 20}deg) rotateX(${-pitch.value / 20}deg)`,
}));

function hotspotStyle(h: any) {
  return {
    left: `${50 + (h.yaw || 0) / 2}%`,
    top: `${50 - (h.pitch || 0) / 2}%`,
  };
}

async function load() {
  list.value = await http.get('/tours');
}
async function create() {
  await http.post('/tours', {
    ...form,
    hotspots: [{ label: '门口', kind: 'info', yaw: -20, pitch: 0 }],
  });
  ElMessage.success('已创建导览');
  form.title = '';
  load();
}
async function preview(row: any) {
  active.value = await http.get(`/tours/${row.id}`);
  yaw.value = active.value.yaw || 0;
  pitch.value = active.value.pitch || 0;
}
async function togglePub(row: any) {
  await http.patch(`/tours/${row.id}`, { published: !row.published });
  load();
}
async function addHotspot(row: any) {
  const { value } = await ElMessageBox.prompt('热点名称', '添加热点');
  await http.post(`/tours/${row.id}/hotspots`, { label: value, yaw: yaw.value, pitch: pitch.value });
  load();
  if (active.value?.id === row.id) preview(row);
}
async function remove(row: any) {
  await http.delete(`/tours/${row.id}`);
  if (active.value?.id === row.id) active.value = null;
  load();
}
function onDragStart(e: PointerEvent) {
  dragging.value = true;
  lastX.value = e.clientX;
  lastY.value = e.clientY;
}
function onDrag(e: PointerEvent) {
  if (!dragging.value) return;
  yaw.value += e.clientX - lastX.value;
  pitch.value = Math.max(-60, Math.min(60, pitch.value + (e.clientY - lastY.value)));
  lastX.value = e.clientX;
  lastY.value = e.clientY;
}
onMounted(load);
</script>

<style scoped>
.hint { color: #6a7b71; margin-top: -8px; }
.tour-stage { margin-top: 20px; }
.stage {
  position: relative;
  height: 360px;
  border-radius: 14px;
  overflow: hidden;
  background-size: cover;
  background-repeat: no-repeat;
  box-shadow: 0 8px 24px rgba(20,40,30,.12);
  touch-action: none;
  user-select: none;
}
.hotspot {
  position: absolute;
  transform: translate(-50%, -50%);
  background: rgba(47,107,79,.92);
  color: #fff;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  white-space: nowrap;
}
.hint-overlay {
  position: absolute;
  left: 12px;
  bottom: 12px;
  background: rgba(0,0,0,.45);
  color: #fff;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 12px;
}
</style>
