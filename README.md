# CareOps Agent SaaS · 智能医养 Agent SaaS 系统

养老机构的多 Agent 工作台。院长可以问「今天院里怎么样」，护工可以口述服药记录，护士可以上传一次就诊的资料。健康助理从当前账号有权查看的记录里取数，经办人在业务页面核对并签认草稿。

[文档导航](docs/README.md) · [部署一家机构](docs/quick-deploy.md) · [接入 MCP 与技能](docs/agent-handbook.md#使用已有-mcp-与社区-skill) · [English](README.en.md)

## 先试一次交班

| 交班时可以这样用 | 工作台会给你什么 |
| --- | --- |
| 问「今天院里怎么样？」 | 汇总授权范围内的在住人数、待办照护、已登记异常和到账情况。 |
| 打开一位长辈的详细档案，进入「近期变化与建议」 | 查看已记录的用餐、活动和照护。点「查看依据」可核对每段的日期和来源。 |
| 上传同一次就诊的照片，或导入一份登记工作簿 | 选定长辈后核对预填资料。就诊原件随病例保存，工作簿用于提取待核对的字段。 |

![健康助理在机构运营总览旁回答「今天院里怎么样」，并提供进入库存台账的按钮](docs/previews/agent-workspace.webp)

*中文工作台实拍。机构与业务数据均为虚构，模型回执为模拟结果。*

主助理处理对话，交班时可让照护与物资 Agent 分别查证。定时巡查按机构设置的周期，逐位读取长辈的签认及观察记录，在档案中整理出有来源的简报。[Agent 手册](docs/agent-handbook.md) · [定时巡查](docs/rounds.md)

## 本机启动

在 Linux 上安装 Python 3.11+、SQLCipher 开发库和 Poppler 后，从仓库根目录运行。以下命令会在独立路径创建虚构机构。首次交互启动时，终端会请你为账号 `owner` 设置密码。

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-storage.txt -r requirements-payments.txt -r requirements-harness.txt -r requirements-a2a.txt
python server.py --db .local/careops-demo.sqlite3 --initial-data demo --port 8765
```

打开[本机工作台](http://localhost:8765/?workspace=1)，从左栏的 **AI** 或右上角的 **健康助理** 开始。模型、OCR 和语音需要已开通的服务；可以先浏览虚构档案、床位与工单。正式机构使用空白加密库、HTTPS 和独立恢复密钥。[服务配置](docs/deployment-console.md) · [正式部署](docs/quick-deploy.md)

## 继续阅读

| 你要做的事 | 从这里开始 |
| --- | --- |
| 办理入住、签认照护、收费退款或处理家属来访 | [员工与家属使用手册](docs/workspace-manual.md) |
| 接入 MCP 工具、复用社区技能、开放 A2A 只读能力 | [Agent 开发与协议导航](docs/README.md#开发与接入-agent) |
| 管理权限、部署设备、备份或升级 | [机构部署与运维导航](docs/README.md#部署与运维) |
| 评估项目能否在持证医养机构上线 | [交付与验收](docs/medical-commercial.md) |

部署时选定机构语种。新增语种默认沿用国际姓名、地址、全球医院目录及 Google Maps，中国版使用高德。项目发布回归只运行中文版及语言无关的公共能力。[测试约定](AGENTS.md) · [维护日志](LOG.md)
