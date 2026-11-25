# CareOps 文档导航

[项目首页](../README.md) · [English](en/README.md)

| 我现在想做什么 | 第一步 |
| --- | --- |
| 第一次登录，试用健康助理 | [在工作台选择入口](workspace-manual.md#从哪里开始) |
| 给一位长辈建档并办理入住 | [从档案选择床位、试住或正式入住](workspace-manual.md#入住床位与档案) |
| 交班时查看一位长辈的健康变化或今日生活 | [在档案中看巡查结果](rounds.md) |
| 让另一个 Agent 接入，查询它有权看的资料 | [开发 Agent 的交接入口](agent-handbook.md#开发与交付-agent-从哪里接手) |
| 把系统部署到一家机构 | [准备主机并创建独立加密库](quick-deploy.md) |

## 员工与家属

| 任务 | 操作说明 |
| --- | --- |
| 接待预约、电话回访、处理家属来访 | [接待与排期](workspace-manual.md#访客意向登记与排期) |
| 建档、上传就诊材料、查过敏或慢性病 | [长辈档案](dossier.md) · [用图片或工作簿预填](agent-handbook.md#用图片或工作簿整理资料) |
| 分配床位、转房、维护楼层或查看平面图 | [楼宇与床位](facility.md) |
| 做评估、调整照护计划、查看个人护理记录 | [分级护理与照护计划](care-pathways.md) · [照护时间线](care-timeline.md) |
| 核对服药、批量派发伙食或巡房 | [服药签认](medication-rounds.md) · [定时工单与批量派发](scheduled-work.md) |
| 核算费用、收款退款、生成报表 | [财务与报表](finance-reports.md) |
| 找不到某个按钮、想了解自己的权限 | [电脑端菜单树](desktop-navigation.md) · [账号与权限](access.md) |

## 开发与接入 Agent

| 任务 | 操作说明 |
| --- | --- |
| 了解主助理与专业 Agent 如何分工、如何验收 | [Agent 手册](agent-handbook.md) · [运行时与检查点](agent-runtime.md) |
| 接入 MCP、Excel 或经审核的社区技能 | [工具与技能配置](assistant-harness.md) · [技能来源](../skills/UPSTREAM.md) |
| 让另一个 Agent 查询院内只读统计 | [A2A Agent Card 与调用方法](agent-protocol.md) |
| 配置云端模型、语音、OCR 或核对用量 | [模型与额度](provider.md) · [语音与影像](media.md) |
| 接入雷达、设备心跳或外部系统 | [第三方接口](integrations.md) · [部署控制台](deployment-console.md) |

## 部署与运维

| 任务 | 操作说明 |
| --- | --- |
| 首次部署、选语种、开启持证机构保全 | [部署指南](quick-deploy.md) · [持证机构上线验收](medical-commercial.md) |
| 配置服务器、端口和设备，接入移动端 | [Owner 控制台](deployment-console.md) · [手机、桌面与小程序](client-compatibility.md) · [客户端运行](clients.md) |
| 做异地加密快照、恢复或签名升级 | [备份与恢复](backups.md) · [存储及密钥](storage.md) · [版本更新](updates.md) |
| 找一笔业务改动或核对审计 | [最近改动与操作记录](history.md) |
| 验收 200 床交付、查既往测试结果 | [商用验收清单](commercial-acceptance.md) · [商用设计](commercial-design.md) · [性能验收](performance-validation.md) · [200 床阶段报告](soak-200-beds-2026-11-25-partial.md) |

[开发规划](roadmap.md) · [中文测试范围](../AGENTS.md) · [项目维护日志](../LOG.md)
