# 平台托管的 AI 套餐

机构按套餐使用云端对话、业务建议、长辈巡查和经办复核。套餐计量包括模型 token、OCR 页数、ASR 录音秒数和朗读字符数。[识别与语音服务](media.md)

## 谁可以做什么

| 身份 | 职责 |
| --- | --- |
| 平台运营方 | 在平台控制的服务器保管供应商凭据，核实客户付款，按机构数据库发放、停用与对账。 |
| 机构总管理员 | 查看本院套餐的到期日、额度、已用量和在途预留量，给员工分配 Agent 和业务域权限。 |
| 获授权员工 | 在任何业务页面使用「健康助理」。服务端依据其账号、岗位和区域选择可用资料。 |
| 家属等其他账号 | 使用各自获授权的机构功能。 |

对外销售采用平台托管服务。每个客户对应独立机构数据库，客户使用浏览器、Electron 或手机入口。供应商密钥在平台后端，机构客户端只持有受限的登录会话。将整个后端、数据库管理员权限及密钥交由客户控制的私有化部署，应另行实施平台托管的计量网关。

## 选择服务商

平台运营方在服务进程环境中设置 `NH_CHAT_PROVIDER` 并重启服务。切换适用于健康助理、业务摘要、巡查、工单建议和相关文字整理。同一进程使用一个对话配置。Owner 在「机构设置」查看当前服务商、模型和套餐用量。

| `NH_CHAT_PROVIDER` | `NH_CHAT_MODEL` | 服务端凭据变量 | 参考 |
| --- | --- | --- | --- |
| `deepseek`（默认） | 固定 `deepseek-flash` | `DEEPSEEK_API_KEY`、运维密库或私有密钥文件 | [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) |
| `openai` | 由运营方填写可用的 Chat Completions 模型 ID | `OPENAI_API_KEY` | [OpenAI API](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create) |
| `anthropic` | 由运营方填写可用的 Claude 模型 ID | `ANTHROPIC_API_KEY` | [Anthropic Messages](https://platform.claude.com/docs/en/api/messages/create) |
| `google` | 由运营方填写可用的 Gemini 模型 ID | `GEMINI_API_KEY`，或 `GOOGLE_API_KEY` | [Google Gemini 兼容接口](https://aistudio.google.com/docs/openai) |

切换前用拟真测试资料核对所选模型的工具调用、结构化输出、增量文本和最终用量回执。部分业务使用较小的可见输出预算。Gemini 推理型号使用最低推理级别，套餐同时预留推理额度。Claude 使用提示指定 JSON，平台校验各业务所需字段。工具参数、权限检查、可打开页面和写入确认均由平台校验。OCR 和公开网页检索各自使用 DeepSeek。ASR 与朗读可以独立选择 DeepSeek、OpenAI 或 HTTP 兼容服务。[识别与语音服务](media.md)

## 开通与对账

1. 启动机构工作台，确定该机构实际使用的 SQLite 文件。
2. 平台运维人员可用 `python3 manage_secrets.py set-deepseek` 将 DeepSeek 凭据写入独立加密运维库，也可在服务环境注入 `DEEPSEEK_API_KEY`。POSIX 主机可以用 `NH_DEEPSEEK_KEY_FILE` 指定服务账号所有、权限为 0600 的普通文件。凭据迁移与独立恢复材料见 [加密存储与恢复](storage.md)。
3. 运营方核实付款及约定的服务期后，在该机构数据库上执行开通命令。下例的额度与日期均为示例，以实际订单为准。

```bash
python3 manage_plan.py --db .local/workspace.sqlite3 grant --name "机构 AI 套餐" --tokens 100000 --expires 2026-12-31
python3 manage_plan.py --db .local/workspace.sqlite3 status
```

额度是当前服务期的 token 总量。有效期内再次执行 `grant` 将调整本期总额并保留原有用量。到期日按上海时区计算，含当日。到期后再次开通产生新服务期，旧用量保留在其原期。额度与供应商账户的人民币余额分别核算。

```bash
python3 manage_plan.py --db .local/workspace.sqlite3 disable
python3 manage_plan.py --db .local/workspace.sqlite3 unsettled
python3 manage_plan.py --db .local/workspace.sqlite3 reconcile --actor ACCOUNT_ID --request REQUEST_ID --tokens CONFIRMED_USAGE
```

`disable` 停止本期的新请求。并发调用在发送前通过 SQLite 写事务预留额度，服务端在网络等待期间释放数据库写锁。成功响应按供应商确认的 token 总量结算，未用的预留额度返还。已明确拒绝的请求释放预留。超时、用量缺失和发送阶段意外重启时保留相应额度。运营方可用 `unsettled` 获取账号、请求编号、时间和预留值，再根据供应商账单用 `reconcile` 录入实际用量。

若运营方已结算而供应商随后才返回不同用量，`unsettled` 会以 `late_receipt` 列出原结算、供应商总量及差额。按原请求号用 `reconcile --tokens` 输入对账确认的**实际总量**。系统保留原结算，另存本次调整。补扣差额在核对前预留，退款差额在核对后释放；同一张迟到回执重复送达只产生一次调整。迟到答复不会写入对话或业务建议。

## 公开网页搜索

在助理对话框底部，点击「朗读」右侧的联网头像。工作台先以机构凭据访问 DeepSeek 官方模型列表，确认可以连接 Flash 后显示「已联网」。开启后可以检索养老机构运营、长护险、照护和相关医疗的公开资料，答复下方列出可点击的来源。连接失败可在同一位置重试。[DeepSeek 模型列表](https://api-docs.deepseek.com/api/list-models/)

| 接口 | 用途 |
| --- | --- |
| `POST /api/assistant/network/probe` | 登录后发送空 JSON 对象。检查机构套餐、服务网络、供应商凭据和模型可用性。成功回传 `connected`、`model`、`checkedAt`。探测只访问固定的官方模型目录。 |
| `POST /api/assistant/chat` | `webSearch: true` 请求本轮公开检索。服务端审核本轮问题与模型选出的原文关键词，剔除无关网页摘录后再整理答复。实际检索的回复带 `webSearched: true` 和 `sources`。来源随答复保存。 |

院内业务、具体个人信息、操作指令和依赖院内上下文的追问仍按原有权限处理。电脑配置等无关问题由工作台直接拒答。搜索方只接收本轮允许公开的关键词，公开答复仅使用本轮筛选后的网页摘录。遇到无匹配来源或连接故障时，工作台会显示相应状态。[官方搜索接口](https://api-docs.deepseek.com/api/search/)

独立搜索和模型 token 分别计量。按本次核对的官方规则，成功返回非空结果时每次计一笔搜索，空结果免费；连接探测不调用推理模型。机构总管理员可在套餐页查看计费搜索次数和待核对次数。运维方可用下列命令按供应商账单核对未明回执。记录用账号及请求号关联，不保存搜索关键词。[DeepSeek 搜索计费说明](https://api-docs.deepseek.com/guides/search/#billing)

```bash
python3 manage_plan.py --db .local/workspace.sqlite3 search-unsettled
python3 manage_plan.py --db .local/workspace.sqlite3 search-reconcile --actor ACCOUNT_ID --request REQUEST_ID --calls 1
```

## 会传给模型的内容

院内对话发送用户本轮的相关问题、当前账号可见的必要业务资料和最近 5 轮已完成问答范围内的有效上下文。界面可回看已存历史。物资与财务简报使用已授权的品目、数量、金额等指标。照护巡查发送当日计划、完成、待办和逾期数量。临床岗位和定时巡查另行生成临床提示，只使用风险登记和体征待复核的标志、已核对的咳嗽时段统计。普通护工的调用仅使用护理进度，二者独立生成和展示。长辈姓名、具体工单的经办人和病历原文不进入巡查提示。文书原件使用独立的 OCR 办理流程。[识别与语音服务](media.md)

关键业务操作提交时，同一数据库事务核对数据约束并保存凭据。后台将业务类别和校验项目送至机构配置的云端模型撰写复核说明。经办人可以在「最近改动」查看独立的云端回执。历史记录和归档老人保留原版本。用量不足、服务超时或无效回复会显示当前状态。自动巡查和复核留在队列等待可用的云服务。

默认 DeepSeek 使用 JSON 输出与非思考模式。截至 2026-11-24，官方 `deepseek-flash` 对应 DeepSeek-V4.1-Flash-1017。平台在聊天请求中显式传入该别名，后续版本以供应商模型表为准。[官方模型表](https://api-docs.deepseek.com/quick_start/pricing/) · [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) · [JSON 输出](https://api-docs.deepseek.com/guides/json_mode/) · [思考模式开关](https://api-docs.deepseek.com/guides/thinking_mode/)

## 验收

```bash
python3 -W error::ResourceWarning -m unittest discover -s tests -p test_provider.py -v
```

模拟供应商响应可重复检验云端开通、请求最小化、并发限额、幂等、撤权、供应商异常、续期和对账。真实凭据联调应使用虚构任务与平台批准的预算。供应商密钥、原始请求、数据库及本地环境文件由部署端保管。

## 按功能与人员查看用量

Owner 在「机构设置 → AI 用量」可按北京时间、功能和经办账号查看汇总与调用明细。自动巡查单列为机构自动任务。涉及员工操作的识别、生成与复核归到发起人。每个云端请求只登记一次，待核对和已确认的用量分别展示。

输入 token 按供应商回执拆分为缓存命中和未命中，输出 token 单列。回执缺少拆分时保留总量并注明缺失。OCR 按页、ASR 按秒、朗读按计费字符、独立搜索按计费次数查看。
