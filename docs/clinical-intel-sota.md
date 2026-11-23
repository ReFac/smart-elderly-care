# 临床智能 · 声学异常 / AI 预诊 · SOTA 接入说明

> 模块：`apps/api/src/clinical-intel`  
> 契约发现：`GET /api/clinical/contract`  
> 状态：**接口已预留 + stub 可演示**；生产级声学/医学模型可替换接入，无需改主业务流。

---

## 1. 目标能力（产品）

| # | 能力 | 当前实现 | 后续 SOTA |
|---|------|----------|-----------|
| 1 | 床头麦克风识别咳嗽；结合历史上下文判断急促型咳嗽 / 明显碰撞（忽略普通软碰撞）；更新老人档案 | Stub 规则 + 档案写入 | 替换 `inferenceBaseUrl` 分类服务 |
| 2 | 识别敏捷度后台可调 | `AcousticSensitivityConfig` + 管理端「识别敏捷度」 | 模型侧读取同一配置 |
| 3 | AI 预诊框一键生成：情况详述、医学建议、风险提示（提示词入库） | Stub 草稿 + `PromptTemplate` | 接院内 LLM / 医学大模型 |
| 4 | 结合近期身体变化做可能性推断；默认推养老院；护工确认后才推家属 | `ClinicalPush` 审批流 | 接微信/短信通道适配器 |
| 5 | 误报/漏报进入学习与噪声，模型持续迭代 | `POST .../events/:id/label` → extensions/agent | 离线重训 / 在线阈值自适应 |

**合规原则**：所有输出为**辅助信息**，不构成诊断或处方；家属侧文案受 `clinical.family_push.v1` 约束。

---

## 2. 数据流（模块化）

```
床头麦克风网关 ──POST /api/clinical/events/ingest──► ClinicalIntelService
                         │
                         ├─► (可选) SOTA POST {inferenceBaseUrl}/v1/acoustic/classify
                         │         或 stubClassify()
                         ├─► AcousticEvent 入库
                         ├─► 病理? → ClinicalFinding + ElderHealth.clinicalNotes
                         └─► 病理? → Alert + ClinicalPush(audience=facility)

管理端「一键生成」──POST /api/clinical/prediagnosis/generate──► PrediagnosisReport
                         │
                         ├─► 读取 PromptTemplate + 档案/体征/事件
                         ├─► 写档案摘要 + 院内推送
                         └─► 家属推送保持 blocked，待
                             POST /api/clinical/pushes/:id/approve-family

人工标注 ──POST /api/clinical/events/:id/label──► 学习提示
                         └─► 建议转发 POST /api/extensions/learning/correct
                             与 POST /api/agent/feedback
```

各 Nest 模块独立：`clinical-intel` 不耦合 UI 框架；Agent Runtime 可通过 bridge 或直连 ingest。

---

## 3. HTTP API 一览

鉴权：除 `GET /api/clinical/contract` 外均需 JWT（管理端 / 服务账号）。

### 3.1 敏捷度与设备

- `GET /api/clinical/config` — 当前灵敏度配置  
- `PUT /api/clinical/config` — 更新（咳嗽灵敏度、急促窗口、硬碰撞阈值、是否忽略软碰撞、SOTA URL 等）  
- `GET|PUT /api/clinical/devices` — 床头麦克风登记  

### 3.2 事件与档案

- `POST /api/clinical/events/ingest`  
  Body 示例：

```json
{
  "elderId": "clx...",
  "deviceId": "mic-a201",
  "bedId": "bed-...",
  "hint": "急促咳嗽",
  "confidence": 0.86,
  "paroxysmal": true,
  "audioUri": "s3://or-local/clip.wav",
  "features": { "embedding_ref": "..." }
}
```

- `GET /api/clinical/events?elderId=`  
- `GET /api/clinical/findings?elderId=`  
- `POST /api/clinical/events/:id/label` `{ "kind": "false_positive"|"false_negative"|"true_positive", "note": "..." }`

### 3.3 AI 预诊

- `POST /api/clinical/prediagnosis/generate` `{ "elderId": "..." }`  
- `GET /api/clinical/prediagnosis?elderId=`  
- `GET /api/clinical/prediagnosis/:id`

### 3.4 推送

- `GET /api/clinical/pushes?audience=facility|family`  
- `POST /api/clinical/pushes/:id/approve-family` — 护工批准推家属（可带 `reportId` 新建）  
- `POST /api/clinical/pushes/:id/reject-family`

### 3.5 提示词

- `GET /api/clinical/prompts`  
- `PUT /api/clinical/prompts` `{ "key", "version", "title", "content" }`

内置 key：

| Key | 用途 |
|-----|------|
| `clinical.prediagnosis.v1` | 一键预诊主提示词 |
| `clinical.risk_hints.v1` | 风险提示写作规范 |
| `clinical.family_push.v1` | 家属推送文案约束 |
| `clinical.acoustic.context.v1` | 上下文判定说明（给模型/规则） |

---

## 4. SOTA 声学模型接入契约

在管理端填写 **SOTA 推理 URL**（`AcousticSensitivityConfig.inferenceBaseUrl`），系统在 ingest 时调用：

`POST {inferenceBaseUrl}/v1/acoustic/classify`

### 请求

```json
{
  "elder_id": "...",
  "bed_id": "...",
  "device_id": "...",
  "audio_uri": "...",
  "features": {},
  "hint": "optional",
  "confidence": 0.0,
  "sensitivity": {
    "coughSensitivity": 0.55,
    "paroxysmalWindowSec": 8,
    "paroxysmalMinCount": 3,
    "hardImpactThreshold": 0.72,
    "softImpactIgnore": true,
    "contextBoost": 0.15
  },
  "context": {
    "note": "可由接入方自行拉取历史；平台也会在预诊阶段合并档案"
  }
}
```

### 响应（建议）

```json
{
  "event_type": "cough",
  "subtype": "paroxysmal_cough",
  "confidence": 0.91,
  "severity": "high",
  "pathological": true,
  "context_score": 0.88,
  "model_id": "your-sota-cough-v3",
  "model_version": "2026.11",
  "note": "短窗内 4 次高能量咳嗽，相对基线 +2.1σ"
}
```

约定：

- `event_type`: `cough` | `impact` | `speech` | `unknown`  
- `subtype`: `paroxysmal_cough` | `mild_cough` | `hard_impact` | `soft_impact` | …  
- **普通软碰撞**：`pathological=false`（或平台在 `softImpactIgnore=true` 时强制忽略）  
- 失败或超时：平台回退 stub，并在事件 `decidedBy=stub` 标明  

### 上下文建议（接入方实现）

1. 拉取该老人近 N 分钟同类型事件密度（急促判定）。  
2. 读取慢病标签（COPD、心衰等）做先验加权。  
3. 碰撞：区分护栏硬碰 vs 日常轻碰（能量/频谱/振动多模态更佳）。  
4. 将可复现特征写入 `features` / 对象存储 URI，便于噪声学习与重训。

---

## 5. AI 预诊 / 医学大模型接入

当前 `generatePrediagnosis` 使用 **stub 组装 + 系统提示词**。替换路径（任选）：

1. **同进程 LLM**：读取 `SystemAiConfig`，把 `clinical.prediagnosis.v1` + 档案上下文发给 chat completions，解析 JSON。  
2. **外部医学模型**：与声学类似，增加 `prediagnosisBaseUrl`（可后续加字段）`POST /v1/clinical/prediagnosis`。  
3. **Agent Skill**：在 `apps/agent` 增加 skill，经 `POST /api/agent/...` bridge 调用。

输出字段必须可映射到：

- `situation` / `medicalAdvice` / `riskHints` / `inferences[]`  
- `facilityAlert` / `familyPushRecommended`

---

## 6. 推送策略（养老院优先）

1. 病理声学事件或预诊 `facilityAlert=true` → **仅院内** `ClinicalPush(audience=facility)` + `Alert`。  
2. 护工在管理端或员工端复核误差。  
3. 确认无误 → `approve-family` → 标记批准（短信/微信公众号通道适配器预留，`channel` 字段）。  
4. 拒绝 → `reject-family`，可进学习队列。

---

## 7. 模型迭代与噪声学习

1. 管理端对事件点「误报/属实」→ `POST /api/clinical/events/:id/label`。  
2. 将 `kind` 转发至现有：  
   - `POST /api/extensions/learning/correct`  
   - `POST /api/agent/feedback`（Agent `alert_feedback` 注入噪声、调阈值）。  
3. 定期导出 `AcousticEvent`（含 `rawJson`/`audioUri`）+ 人工标签做离线重训。  
4. 新模型版本写入响应 `model_id`/`model_version`，平台原样落库，支持 A/B。

---

## 8. 管理端入口

- 路由：`/clinical-intel`（功能注册表可搜索「咳嗽」「预诊」）  
- Tab：识别敏捷度 | 事件模拟 | AI 预诊框 | 推送/提示词  

演示账号：`admin` / `123456`。

---

## 9. 敏捷开发约定

- **新模型 = 新服务**，只改配置 URL，不改 Nest 主流程。  
- **新提示词 = 新 `PromptTemplate` 版本**，key 保持稳定。  
- **新通道 = ClinicalPush.channel 适配器**，审批状态机不变。  
- Schema 变更集中在 `clinical-intel` 相关 Prisma model，避免跨域大爆炸。

---

## 10. 验收清单（预留阶段）

- [x] 配置可读写  
- [x] ingest 可产生事件；急促咳嗽/硬碰撞写档案；软碰撞不病理  
- [x] 一键预诊产出情况/建议/风险/推断  
- [x] 院内推送自动；家属需批准  
- [x] 提示词入库可查  
- [x] 本文档与 `GET /api/clinical/contract` 一致  
- [ ] 真实麦克风 SDK  
- [ ] 生产 SOTA 分类服务  
- [ ] 生产医学 LLM JSON 严格模式  
- [ ] 微信/短信实发适配器  

---

## 11. 相关代码路径

| 路径 | 说明 |
|------|------|
| `apps/api/src/clinical-intel/` | Nest 模块 |
| `apps/api/src/clinical-intel/prompts.ts` | 内置提示词 |
| `apps/admin/src/views/ClinicalIntel.vue` | 管理端 |
| `apps/agent/app/skills/acoustic_anomaly/` | Agent 侧 stub skill |
| `packages/shared/src/registry.ts` | 功能注册 `clinical_intel` |
