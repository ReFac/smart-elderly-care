<template>
  <div class="tour-page">
    <div class="topbar">
      <h1>房态导览</h1>
      <p>全景 / 简易 3D · 手机与微信公众号可拖拽浏览</p>
    </div>

    <div class="card" v-if="!active">
      <h3>已发布场景</h3>
      <button
        v-for="t in list"
        :key="t.id"
        class="tour-item"
        type="button"
        @click="open(t)"
      >
        <span>{{ t.title }}</span>
        <span class="chip">{{ typeLabel(t.sceneType) }}</span>
      </button>
      <p v-if="!list.length" class="muted">暂无公开导览</p>
    </div>

    <div v-else class="viewer">
      <div class="viewer-bar">
        <button class="btn secondary back" type="button" @click="active = null">返回列表</button>
        <strong>{{ active.title }}</strong>
      </div>
      <div
        class="stage"
        :style="stageStyle"
        @pointerdown="onDragStart"
        @pointermove="onDrag"
        @pointerup="endDrag"
        @pointercancel="endDrag"
        @pointerleave="endDrag"
      >
        <button
          v-for="h in active.hotspots || []"
          :key="h.id"
          class="hotspot"
          type="button"
          :style="hotspotStyle(h)"
          @click.stop="onHotspot(h)"
        >
          {{ h.label }}
        </button>
        <div class="hint-overlay">单指拖动旋转 · {{ yaw.toFixed(0) }}° / {{ pitch.toFixed(0) }}°</div>
      </div>
      <p v-if="tip" class="card tip">{{ tip }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import http from '../api';

const list = ref<any[]>([]);
const active = ref<any>(null);
const yaw = ref(0);
const pitch = ref(0);
const dragging = ref(false);
const lastX = ref(0);
const lastY = ref(0);
const tip = ref('');

const stageStyle = computed(() => ({
  backgroundImage: `url(${active.value?.sceneUrl || ''})`,
  backgroundPosition: `${50 + yaw.value / 3}% ${50 + pitch.value / 3}%`,
  transform: `perspective(720px) rotateY(${yaw.value / 22}deg) rotateX(${-pitch.value / 22}deg)`,
}));

function typeLabel(t: string) {
  if (t === 'model3d') return '3D';
  if (t === 'floorplan') return '平面';
  return '全景';
}
function hotspotStyle(h: any) {
  return {
    left: `${50 + (h.yaw || 0) / 2}%`,
    top: `${50 - (h.pitch || 0) / 2}%`,
  };
}
async function load() {
  list.value = await http.get('/tours/public');
}
async function open(t: any) {
  active.value = await http.get(`/tours/public/${t.id}`);
  yaw.value = active.value.yaw || 0;
  pitch.value = active.value.pitch || 0;
  tip.value = '';
}
function onHotspot(h: any) {
  tip.value = h.payloadJson ? `热点：${h.label} · ${h.payloadJson}` : `热点：${h.label}`;
}
function onDragStart(e: PointerEvent) {
  dragging.value = true;
  lastX.value = e.clientX;
  lastY.value = e.clientY;
  (e.currentTarget as HTMLElement)?.setPointerCapture?.(e.pointerId);
}
function onDrag(e: PointerEvent) {
  if (!dragging.value) return;
  yaw.value += e.clientX - lastX.value;
  pitch.value = Math.max(-55, Math.min(55, pitch.value + (e.clientY - lastY.value)));
  lastX.value = e.clientX;
  lastY.value = e.clientY;
}
function endDrag() {
  dragging.value = false;
}
onMounted(load);
</script>

<style scoped>
.tour-item {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  border: none;
  background: #f3f8f5;
  border-radius: 12px;
  padding: 12px;
  margin-bottom: 8px;
  font: inherit;
  color: inherit;
  text-align: left;
}
.viewer-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px 0;
}
.back {
  width: auto;
  padding: 8px 12px;
}
.stage {
  margin: 12px 16px;
  height: min(58vh, 420px);
  border-radius: 16px;
  overflow: hidden;
  background-size: cover;
  background-repeat: no-repeat;
  background-color: #1a2a22;
  position: relative;
  touch-action: none;
  user-select: none;
  -webkit-user-select: none;
  box-shadow: 0 8px 24px rgba(20, 40, 30, 0.12);
}
.hotspot {
  position: absolute;
  transform: translate(-50%, -50%);
  border: none;
  background: rgba(47, 107, 79, 0.92);
  color: #fff;
  padding: 6px 10px;
  border-radius: 999px;
  font-size: 12px;
  white-space: nowrap;
}
.hint-overlay {
  position: absolute;
  left: 10px;
  bottom: 10px;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  padding: 6px 10px;
  border-radius: 8px;
  font-size: 12px;
}
.tip {
  margin-top: 0;
}
</style>
