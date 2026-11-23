# 智能养老管理项目（Smart Elderly Care）

> **给后续 SOTA / 高级模型的接手说明**  
> 本文整理截至 `33728f9`（2026-11-23）的架构、进度、预留接口与替换点。  
> 仓库：[ReFac/smart-elderly-care](https://github.com/ReFac/smart-elderly-care)  
> 临床声学 / 预诊专项契约：[`docs/clinical-intel-sota.md`](docs/clinical-intel-sota.md)

本地可运行的养老院 **一体化主控台**：运营业务 CRUD、家属/员工移动端、Python Agent Runtime、临床智能（声学异常 + AI 预诊）接口预留、右侧 Codex 风格 Agent、高权限密码确认。

---

## 1. 一句话目标

用 **模块化、可热配、可替换模型** 的方式，把养老院运营、照护、医护、家属透明、床头感知与 Agent 编排放在同一产品里；生产级 ASR / 咳嗽检测 / 医学 LLM 等 **SOTA 以独立服务接入**，不改主业务状态机。

---

## 2. 基础架构

### 2.1 拓扑

```text
┌─────────────────┐   ┌──────────────────┐   ┌────────────────────┐
│ Admin :5173     │   │ Family H5 :5174  │   │ Desktop (Electron) │
│ Vue3 + EP       │   │ 手机/微信优先     │   │ 壳加载 Admin       │
│ 右侧 Agent Rail │   │ 导览公开可免登    │   └────────────────────┘
└────────┬────────┘   └────────┬─────────┘
         │ /api proxy          │ /api proxy
         ▼                     ▼
┌──────────────────────────────────────────┐
│ NestJS API :3000/api                     │
│ Prisma · SQLite(dev) / Postgres(opt)     │
│ control · portal · tours · clinical · …  │
└───────────────────┬──────────────────────┘
                    │ AGENT_BASE_URL
                    ▼
┌──────────────────────────────────────────┐
│ Python Agent Runtime :8100               │
│ Harness · MCP · Hook · Skill · DeepSeek  │
└──────────────────────────────────────────┘
         ▲
         │ 可选 SOTA
┌────────┴─────────┐  ┌────────────────────┐
│ Acoustic SOTA    │  │ Medical / LLM SOTA │
│ /v1/acoustic/…   │  │ 预诊 JSON 契约     │
└──────────────────┘  └────────────────────┘
```

### 2.2 Monorepo 布局

```text
nursing-home/
├── apps/
│   ├── api/          # NestJS 业务 API + Prisma
│   ├── admin/        # 管理主控台（2026 UI + Agent 侧栏）
│   ├── family/       # 用户/家属/护理员 H5（移动 + 微信公众号适配）
│   ├── agent/        # Python Agent Runtime
│   └── desktop/      # Electron 壳
├── packages/
│   └── shared/       # FEATURE_REGISTRY、枚举、模糊搜索
├── docs/
│   └── clinical-intel-sota.md   # 声学/预诊 SOTA 接入全文
├── pnpm-workspace.yaml
└── package.json      # dev / db:setup 脚本
```

### 2.3 技术栈

| 层 | 技术 |
|---|---|
| 包管理 | pnpm workspace（`@nh/api` `@nh/admin` `@nh/family` `@nh/shared` …） |
| API | NestJS 10、Prisma 6、JWT、class-validator |
| DB | 默认 SQLite `apps/api/prisma/dev.db`；可选 Postgres + Redis（`docker-compose.yml`） |
| Admin | Vue 3、Vite 6、Element Plus、Pinia、Vue Router |
| Family | Vue 3 移动 H5（Chrome / Safari / 微信内置浏览器） |
| Agent | FastAPI、Harness/MCP/Skill、可选 DeepSeek（OpenAI 兼容） |
| 共享 | `packages/shared` 功能注册表，驱动侧栏与模糊搜索 |

### 2.4 端口与账号

| 服务 | 地址 |
|---|---|
| API | http://localhost:3000/api |
| Admin | http://localhost:5173 |
| Family | http://localhost:5174 |
| Agent | http://localhost:8100 |

演示密码均为 **`123456`**：

| 账号 | 角色 | 入口 |
|---|---|---|
| `admin` | 主管理员 | Admin |
| `nurse` | 护士 | Admin |
| `caregiver` | 护理员 | Family 照护 |
| `finance` | 财务 | Admin |
| `family` | 家属 | Family 账单/餐食/导览 |

种子：216 床、多栋楼、演示老人、当日照护、账单、食谱、导览、临床提示词与灵敏度默认配置。

---

## 3. 快速启动

```bash
export PATH="$HOME/.local/bin:$PATH"
cd nursing-home
pnpm install
pnpm --filter @nh/shared build
pnpm db:setup          # prisma generate + db push + seed
pnpm dev               # API :3000 + Admin :5173 + Family :5174

# 可选
pnpm dev:agent         # Agent :8100
pnpm dev:desktop       # Electron（需先有 Admin）
```

代理推送 GitHub 若超时，可按环境使用本地 HTTP 代理（本机常见 `http://127.0.0.1:7897`）。

---

## 4. 进度总览（成熟度）

图例：`✅` 可用 · `◐` Stub/预留可演示 · `⬜` 未做

| 域 | 状态 | 说明 |
|---|---|---|
| 认证 JWT / 角色 | ✅ | 登录、`/auth/me`、高权限 `POST /auth/reauth` |
| 组织床位楼栋 | ✅ | 216 床种子、床态视图 |
| 老人档案 | ✅ | 建档、健康、合同、调床、情绪记录 |
| 照护计划/打卡/工单/探视 | ✅ | 核心流程可跑 |
| 收费账单/缴费 | ✅ | 含家属透明账单 |
| 食堂餐食 | ✅ | 周食谱、忌口 |
| 医护体征/药品/医嘱等 | ✅ | CRUD 脚手架，可深化 |
| 长护险 | ✅ | 评估/留痕/对账导出脚手架 |
| 物资 / 人事 / 安防 / 报表 | ✅ | 模块 + CRUD |
| 功能注册表 + 模糊搜索 | ✅ | `@nh/shared` + `/api/extensions/search` |
| 学习与噪声 | ✅ | 人工修正 → 噪声样本；对接 Agent feedback |
| Control Plane | ✅ | 变量 / 服务 / API 元数据热配 |
| Portal 用户/员工 | ✅ | `/portal/user/home`、`/portal/employee/home` |
| 3D/全景房态导览 | ✅ | 管理端 + 公开 `/tours/public`；简易拖拽舞台 |
| Family 移动/微信适配 | ✅ | viewport、safe-area、微信 UA、导览 Tab |
| 临床智能（咳嗽/碰撞/预诊） | ◐ | 完整 API + stub 分类/预诊；**等 SOTA** |
| Admin 2026 UI + Agent 侧栏 | ✅ | Codex 风格；高权限甄别框 + 密码 |
| OCR / 支付 / GPS / 硬件 webhook | ◐ | 接口占位 |
| 真麦克风 SDK / 微信实发 / 小程序 | ⬜ | 通道适配器未接 |
| 生产医学 LLM 严格 JSON | ⬜ | 现用 stub 组装 + PromptTemplate |

### 提交里程碑（main）

| Commit | 内容 |
|---|---|
| `9bda45a` | MVP：档案/床位/照护/账单/餐食 |
| `d1f9b4d` | 九大业务域脚手架 CRUD |
| `b4fc58b` | Python Agent Runtime |
| `0cf8df4` | 统一主控台、模糊搜索、噪声学习 |
| `f5f6281` | Control Plane、Portal、3D Tour |
| `bacf0e2` | 临床智能接口预留 + SOTA 文档 |
| `33728f9` | 管理端 UI 重构 + 右侧 Agent + 高权限确认 |

---

## 5. API 模块地图（Nest）

前缀均为 `/api`。源码：`apps/api/src/<module>/`。

| 前缀 | 职责 |
|---|---|
| `/auth` | 登录、me、**reauth（高权限）** |
| `/org` | 楼栋/楼层/房间/床位 |
| `/elders` | 老人档案 |
| `/care` | 照护 |
| `/billing` `/meals` | 财务、食堂 |
| `/medical` `/ltc` | 医护、长护险 |
| `/inventory` `/hr` `/security` `/reports` | 后勤、人事、安防、报表 |
| `/dashboard` `/settings` | 看板、设置 |
| `/ai` `/payment` `/gps` `/upload` | 预留 / 上传 |
| `/extensions` | 功能目录、动态注册、**learning** |
| `/agent` | 桥接 Python Agent；**`/agent/console/chat|execute`** |
| `/control` | 变量、服务、API 元数据总控 |
| `/portal` | 用户端 / 员工端聚合 |
| `/tours` | 3D/全景导览（含 public） |
| `/clinical` | 声学事件、预诊、推送、提示词、敏捷度 |

发现契约（无需业务背景）：

- `GET /api/clinical/contract`
- `GET /api/agent/manifest`（需 Agent 进程）
- Admin 功能树：`packages/shared/src/registry.ts`

---

## 6. 关键设计要点（接手必读）

### 6.1 模块化与敏捷

- **一域一 Nest Module**，避免跨域大爆炸改 Prisma。
- 运行参数优先进 **`SystemVariable` / `AcousticSensitivityConfig` / `PromptTemplate`**，少改代码。
- 新功能登记 **`FEATURE_REGISTRY`**，侧栏与搜索自动出现。
- 新模型 = **新 HTTP 服务 + 填 URL**（如 `inferenceBaseUrl`），主流程只认统一 JSON。

### 6.2 Control Plane

管理端路径：`/control-plane`  
API：`/api/control/snapshot|variables|services|apis`  
可改：品牌/Agent/家属/移动/临床等运行变量；服务启停与探测；API 元数据启停。

### 6.3 临床智能（SOTA 主替换面）

管理端：`/clinical-intel`  
文档：[docs/clinical-intel-sota.md](docs/clinical-intel-sota.md)

流水线：

1. 麦克风网关 → `POST /api/clinical/events/ingest`
2. 若配置了 `inferenceBaseUrl` → `POST {url}/v1/acoustic/classify`，否则 stub
3. 病理事件 → `ClinicalFinding` + 更新 `ElderHealth.clinicalNotes`
4. 默认 **院内** `ClinicalPush` + `Alert`；家属须 `approve-family`
5. `POST /api/clinical/prediagnosis/generate` 一键预诊（提示词已入库）
6. 误报标注 → `/clinical/events/:id/label` → 建议转发 learning / agent feedback

**Stub 行为（勿当生产模型）**：急促咳嗽 / 硬碰撞 → pathological；软碰撞默认忽略。

### 6.4 Admin Agent 侧栏（类 Codex）

- UI：`apps/admin/src/components/AgentRail.vue`
- 对话：`POST /api/agent/console/chat`
- 高权限执行：`POST /api/agent/console/execute`
- 流程：Agent 产出 `ProposedAction`（含 `changes[]` before/after）→ **甄别框** → **每次管理员密码**（`/auth/reauth` 发 120s elevate token）→ 执行
- 试指令：「调整咳嗽灵敏度」「停用 agent 服务」「打开临床智能」

### 6.5 Python Agent Runtime

详见 [`apps/agent/README.md`](apps/agent/README.md)。

能力摘要：感知融合、语音照护、会议纪要、床位记忆、分级路由、告警反馈噪声、Typeless、健康自动草稿、`acoustic_anomaly` skill（转发 Nest clinical）。

策略：`apps/agent/policies/runtime.yaml`  
环境：`apps/agent/.env.example`（`LLM_API_KEY`、`NEST_TOKEN` 等）

### 6.6 家属 / 员工端

- 手机优先；Safari / Chrome；微信 UA 增加底部安全区。
- Tab：首页 / **导览** / 账单 / 餐食 / 照护。
- `/tour` 可走公开导览 API；业务页需登录。
- 聚合：`/api/portal/user/home`、`/employee/home`。

---

## 7. 数据模型（与 SOTA 相关的表）

Prisma：`apps/api/prisma/schema.prisma`

| 模型 | 用途 |
|---|---|
| `AcousticDevice` | 床头麦登记 |
| `AcousticEvent` | 咳嗽/碰撞等事件 + modelId/version |
| `ClinicalFinding` | 病理性特征 → 档案 |
| `PrediagnosisReport` | AI 预诊草稿 |
| `ClinicalPush` | 院内/家属推送与审批 |
| `PromptTemplate` | 系统提示词（可后台改） |
| `AcousticSensitivityConfig` | 灵敏度 + SOTA URL |
| `SystemVariable` / `ServiceRegistry` / `ApiEndpointMeta` | 总控 |
| `RoomTour` / `RoomTourHotspot` | 导览 |
| `ElderHealth.clinicalNotes` / `acousticRiskTags` | 自动维护摘要 |

重置开发库：

```bash
rm -f apps/api/prisma/dev.db*
pnpm db:setup
```

---

## 8. SOTA / 高级模型接手清单

按优先级建议：

1. **声学分类服务**  
   实现 `POST /v1/acoustic/classify`（契约见 clinical 文档）→ Admin 填 `inferenceBaseUrl`。  
   验收：急促咳嗽病理写档案；软碰撞不病理；`model_id` 落库。

2. **医学预诊 LLM**  
   消费 `clinical.prediagnosis.v1` + 档案/体征/事件上下文，严格输出 JSON  
   （`situation` / `medicalAdvice` / `riskHints` / `inferences`）。  
   替换点：`ClinicalIntelService.generatePrediagnosis` 内 stub。

3. **噪声学习闭环**  
   导出 `AcousticEvent` + 人工 label，离线重训；在线调阈可接现有 Agent `alert_feedback`。

4. **通道适配器**  
   `ClinicalPush.channel`：微信公众号 / 短信实发；审批状态机已具备。

5. **真设备**  
   床头麦 SDK → ingest（带 `audioUri` / `features`）；设备表已有。

6. **Agent 侧栏增强**  
   将 `console/chat` 从规则意图升级为工具调用型（仍必须走 privilege 甄别框）。

**不要做的事（除非产品明确要求）**

- 让模型直接写死诊断结论或自动给家属发「确诊」文案。  
- 绕过 `approve-family` 推家属。  
- 在业务 Module 里硬编码厂商 SDK（应放独立服务）。

---

## 9. 演示路径（回归）

1. `admin` 登录 → 新 UI 看板；右侧 Agent 开着。  
2. Agent 输入「调整咳嗽灵敏度」→ 甄别框 → 密码 `123456` → 执行。  
3. `/clinical-intel` 模拟急促咳嗽 / 软碰撞；老人详情「一键 AI 预诊」。  
4. `/room-tours` 发布场景；Family `/tour` 拖拽浏览。  
5. `/control-plane` 改变量、探测服务。  
6. `family` 看账单；`caregiver` 打卡。  
7. （可选）`pnpm dev:agent` → `/agent` 页与 manifest。

---

## 10. 文档索引

| 文档 | 内容 |
|---|---|
| **本 README** | 架构、进度、接手总览 |
| [docs/clinical-intel-sota.md](docs/clinical-intel-sota.md) | 声学/预诊/推送/学习完整契约 |
| [apps/agent/README.md](apps/agent/README.md) | Agent Runtime 启动与能力 |
| `packages/shared/src/registry.ts` | 功能与路由真源 |
| `apps/api/prisma/schema.prisma` | 数据真源 |

---

## 11. 可选：切换 PostgreSQL

1. `docker compose up -d`  
2. `apps/api/.env` 中 `DATABASE_URL` 改为  
   `postgresql://nursing:nursing@localhost:5432/nursing_home`  
3. `schema.prisma` 的 `provider` 改为 `postgresql`  
4. `pnpm db:setup`

---

## 12. 产品分期（历史规划，可按 SOTA 插入）

- **已完成主线**：MVP → 九域 CRUD → Agent → 统一主控台 → Control/Portal/Tour → 临床预留 → 2026 Admin UI  
- **下一步（模型侧）**：声学 SOTA、医学 LLM、通道实发  
- **再下一步（产品侧）**：小程序/鸿蒙、支付生产、GPS 围栏、硬件 webhook 实装  

---

## 13. 合规与安全摘要

- 预诊 / 声学输出均为 **辅助信息**，不构成诊断或处方。  
- 高权限控制台操作：**变更甄别 + 每次管理员密码**。  
- 家属通知默认关闭，须院内人员批准。  
- JWT Secret / LLM Key 仅存环境变量；勿提交 `.env`。
