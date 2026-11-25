# 平台托管的 AI 套餐

[文档导航](README.md)

机构按套餐使用云端对话、业务建议、长辈巡查和经办复核。套餐计量包括模型 token、OCR 页数、ASR 录音秒数和朗读字符数。[识别与语音服务](media.md)

## 谁可以做什么

| 身份 | 职责 |
| --- | --- |
| 平台运营方 | 在平台控制的服务器保管供应商凭据，核实客户付款，按机构数据库发放、停用与对账。 |
| 机构总管理员 | 查看本院套餐的到期日、额度、已用量和在途预留量，给员工分配 Agent 和业务域权限。 |
| 获授权员工 | 在任何业务页面使用「健康助理」。服务端依据其账号、岗位和区域选择可用资料。 |
| 家属等其他账号 | 使用各自获授权的机构功能。 |

对外销售时，每个客户使用独立的机构数据库，通过浏览器、Electron 或手机登录。平台后端保管供应商密钥，机构客户端只保留受限的登录会话。如果私有化部署把整个后端、数据库管理员权限和密钥都交给客户，应另行部署由平台托管的计量网关。

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

额度指当前服务期可用的 token 总量。有效期内再次执行 `grant` 只调整总额，已使用的部分仍计入本期。到期日按上海时区计算，当天仍有效。到期后重新开通会产生新的服务期，旧用量留在原期。机构套餐额度和供应商账户的人民币余额各自核算。

### 院区不限量

平台运营方可为单个院区开通长期不限量。对话、后台 AI 任务、OCR、语音识别、朗读和联网检索继续按员工、功能记录实际用量。供应商按实际调用计费。切换后可在机构设置中查看「不限量」及累计使用量。

```bash
python3 manage_plan.py --db .local/workspace.sqlite3 unlimited
python3 manage_plan.py --db .local/workspace.sqlite3 status
```

命令只作用于指定的机构数据库，原有用量和待对账记录继续保留。对外销售的机构可以通过 `grant` 按其订单设置服务期和额度。

```bash
python3 manage_plan.py --db .local/workspace.sqlite3 disable
python3 manage_plan.py --db .local/workspace.sqlite3 unsettled
python3 manage_plan.py --db .local/workspace.sqlite3 reconcile --actor ACCOUNT_ID --request REQUEST_ID --tokens CONFIRMED_USAGE
```

`disable` 会停止本期的新请求。并发请求在发送前通过 SQLite 写事务预留额度，等待网络响应时不占数据库写锁。供应商确认成功后，服务端按回执中的 token 总量结算，返还未用部分。明确拒绝的请求释放预留。发生超时、回执缺少用量或发送时意外重启，相关额度继续保留。运营方先用 `unsettled` 查账号、请求编号、时间和预留值，再对照供应商账单，用 `reconcile` 录入实际用量。

人工结算后，如果供应商才返回不同的用量，`unsettled` 中会出现 `late_receipt`，列出原结算、供应商总量及差额。按原请求号执行 `reconcile --tokens`，输入对账确认的**实际总量**。系统会保留原结算并单列调整。需补扣的差额在核对前预留，需退还的差额在核对后释放。同一迟到回执重复送达只调整一次，迟到的答复不会写入对话或业务建议。

## 公开网页搜索

在助理对话框底部，点击「朗读」右侧的联网头像。工作台先以机构凭据访问 DeepSeek 官方模型列表，确认可以连接 Flash 后显示「已联网」。开启后可以检索养老机构运营、长护险、照护和相关医疗的公开资料，答复下方列出可点击的来源。连接失败可在同一位置重试。[DeepSeek 模型列表](https://api-docs.deepseek.com/api/list-models/)

| 接口 | 用途 |
| --- | --- |
| `POST /api/assistant/network/probe` | 登录后发送空 JSON 对象。检查机构套餐、服务网络、供应商凭据和模型可用性。成功回传 `connected`、`model`、`checkedAt`。探测只访问固定的官方模型目录。 |
| `POST /api/assistant/chat` | `webSearch: true` 请求本轮公开检索。服务端审核本轮问题与模型选出的原文关键词，剔除无关网页摘录后再整理答复。实际检索的回复带 `webSearched: true` 和 `sources`。来源随答复保存。 |

涉及院内业务、个人资料、操作指令或需要院内上下文的追问时，助理按员工原有权限处理。遇到电脑配置等无关问题，工作台直接拒答。搜索服务只收到本轮允许公开的关键词，助理只使用本轮筛选后的网页摘录回答公开问题。找不到匹配来源或连接失败时，工作台会提示具体状态。[官方搜索接口](https://api-docs.deepseek.com/api/search/)

独立搜索和模型 token 分别计量。按本次核对的官方规则，成功返回非空结果时每次计一笔搜索，空结果免费；连接探测不调用推理模型。机构总管理员可在套餐页查看计费搜索次数和待核对次数。运维方可用下列命令按供应商账单核对未明回执。记录用账号及请求号关联，不保存搜索关键词。[DeepSeek 搜索计费说明](https://api-docs.deepseek.com/guides/search/#billing)

```bash
python3 manage_plan.py --db .local/workspace.sqlite3 search-unsettled
python3 manage_plan.py --db .local/workspace.sqlite3 search-reconcile --actor ACCOUNT_ID --request REQUEST_ID --calls 1
```

## 会传给模型的内容

院内对话只发送本轮相关问题、当前账号有权查看的必要业务资料，以及最近 5 轮已完成问答中的有效上下文。已存的更早对话仍可在界面上查看。物资和财务简报使用获准的品目、数量、金额等指标。照护巡查发送当日计划数、完成数、待办数和逾期数。

普通护工看到的巡查只使用护理进度。临床岗位和定时巡查另行生成、展示临床提示，依据限于风险登记标志、待复核体征标志及已核对的咳嗽时段统计。巡查提示不含长辈姓名、具体工单的经办人或病历原文。要处理文书原件，请使用独立的 OCR 流程。[识别与语音服务](media.md)

关键业务操作提交时，同一数据库事务核对数据约束并保存凭据。后台将业务类别和校验项目送至机构配置的云端模型撰写复核说明。经办人可以在「最近改动」查看独立的云端回执。历史记录和归档老人保留原版本。用量不足、服务超时或无效回复会显示当前状态。自动巡查和复核留在队列等待可用的云服务。

默认 DeepSeek 使用 JSON 输出与非思考模式。截至 2026-11-24，官方 `deepseek-flash` 对应 DeepSeek-V4.1-Flash-1017。平台在聊天请求中显式传入该别名，后续版本以供应商模型表为准。[官方模型表](https://api-docs.deepseek.com/quick_start/pricing/) · [Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/) · [JSON 输出](https://api-docs.deepseek.com/guides/json_mode/) · [思考模式开关](https://api-docs.deepseek.com/guides/thinking_mode/)

## 验收

```bash
python3 -W error::ResourceWarning tests/run.py -p test_provider.py -v
```

模拟供应商响应可重复检验云端开通、请求最小化、并发限额、幂等、撤权、供应商异常、续期和对账。真实凭据联调应使用虚构任务与平台批准的预算。供应商密钥、原始请求、数据库及本地环境文件由部署端保管。

## 按功能与人员查看用量

Owner 可打开「机构设置 → AI 用量」，按北京时间、功能和经办账号查汇总，再查看单次调用明细。员工发起的识别、生成和复核计在发起人名下，自动巡查单列为机构自动任务。每个云端请求只登记一次，已确认用量和待核对用量分开显示。

查看输入 token 时，可分别看到供应商回执中的缓存命中量和未命中量。若供应商没给出拆分，界面保留总量并标注缺失。输出 token 另列。OCR 看页数，ASR 看秒数，朗读看计费字符，独立搜索看计费次数。
