# Skill: acoustic_anomaly

床头麦克风声学异常（咳嗽 / 碰撞）分类与上报。

## 状态

接口预留。默认转发业务 API `POST /api/clinical/events/ingest`；若配置了本地 SOTA，可先分类再上报。

## 输入

- elder_id, bed_id, device_id
- audio_uri 或 features
- hint / confidence（可选）

## 输出

- classification + clinical API 回执

## 学习

人工修正走 `alert_feedback` / 业务 `clinical/events/:id/label`。

完整契约见仓库 `docs/clinical-intel-sota.md`。
