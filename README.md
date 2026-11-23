# 智能养老管理项目 · MVP

可运行的养老院管理平台：老人档案、床位、照护工单、收费账单、食堂餐食、家属端透明账单；医护/长护险/物资/人事/安防等模块侧栏占位 + API stub；OCR/LLM、支付、GPS 接口已预留。

## 技术栈

| 层 | 技术 |
|---|---|
| Monorepo | pnpm workspace |
| 后端 | NestJS + Prisma + SQLite（本地零依赖）；`docker-compose.yml` 可选 PostgreSQL/Redis |
| 管理端 | Vue 3 + Element Plus（响应式） |
| 桌面端 | Electron 壳加载管理端 |
| 家属/护理端 | Vue 3 移动 H5（微信小程序可后续迁 uni-app） |

## 快速启动

```bash
export PATH="$HOME/.local/bin:$PATH"
cd nursing-home
pnpm install
pnpm --filter @nh/shared build
pnpm db:setup          # prisma generate + db push + seed
pnpm dev               # 同时启动 API :3000 / Admin :5173 / Family :5174
```

可选桌面端（需先起 admin）：

```bash
pnpm dev:desktop
```

## 演示账号（密码均为 `123456`）

| 账号 | 角色 | 入口 |
|---|---|---|
| `admin` | 管理员 | http://localhost:5173 |
| `nurse` | 护士 | 管理端 |
| `caregiver` | 护理员 | http://localhost:5174 照护打卡 |
| `finance` | 财务 | 管理端收费 |
| `family` | 家属 | http://localhost:5174 账单/餐食 |

种子数据含 **216 张床**（A/B 两栋）、5 位演示老人、当日照护任务、当月账单、7 日食谱。

## 演示路径

1. `admin` 登录 → 运营看板查看入住率/欠费/待办  
2. 老人档案 → 新建或 OCR 辅助建档 → 分床  
3. 照护服务 → 生成今日任务 / 打卡 / 探视登记  
4. 收费财务 → 生成本月账单 → 登记缴费  
5. `family` 登录家属端 → 查看账单明细与今日餐食  
6. `caregiver` 登录 → 照护页打卡  

## 模块地图

**九大业务域（脚手架 + CRUD，核心流程加深）：**

| 域 | 能力 |
|---|---|
| 老人档案 | 建档/健康/合同/调床 |
| 照护服务 | 计划/打卡/工单/探视 |
| 医护健康 | 体征、药品、发药、体检随访、医嘱转诊 |
| 长护险 | 评估、服务项目、留痕、对账、申报导出 |
| 收费财务 | 计费/账单/缴费/押金 |
| 后勤物资 | 库存出入库、低库存、报修 |
| 人事排班 | 员工、排班、考勤、绩效统计 |
| 安防告警 | 告警中心、风险扫描、门禁、硬件 webhook |
| 报表看板 | 运营看板、民政月报表生成/导出 |
| Agent 智能体 | Python Harness/MCP/Hook/Skill 运行时（8100） |

**Agent Runtime（`apps/agent`，Python）**
- 多源感知融合、语音增量照护、会议纪要、床位记忆、分级路由、告警反馈自迭代
- Harness 护栏 + 全链路审计 + 人工复核队列
- MCP 工具底座；Typeless 全语音入口；DeepSeek OpenAI 兼容
- 启动：`pnpm dev:agent` → http://localhost:8100/v1/manifest
- **统一主控台**（管理端 :5173）：运营 / 医护 / 家属视角 / 护理视角 / Agent / 学习噪声 / 扩展注册合一
- 顶部支持功能与设置**模糊搜索**；`/api/extensions/*` 预留新接口扩展；人工修正后自动加噪声学习

**接口预留：** `POST /api/ai/ocr`、`POST /api/ai/extract-form`、`POST /api/payment/checkout`、`POST /api/gps/webhook`、`POST /api/security/hardware/webhook`

## 切换 PostgreSQL（可选）

1. `docker compose up -d`  
2. 将 `apps/api/.env` 中 `DATABASE_URL` 改为  
   `postgresql://nursing:nursing@localhost:5432/nursing_home`  
3. 把 `schema.prisma` 的 `provider` 改为 `postgresql` 后执行 `pnpm db:setup`

## 后续分期

- **P2** 发药/体征、长护险评估对账、物资深化  
- **P3** 排班绩效、安防硬件、OCR 生产供应商  
- **P4** 支付对接、GPS 围栏、微信小程序、鸿蒙/安卓原生  
