# 文书识别、语音转写与朗读

医疗文书使用 DeepSeek OCR。语音转写与朗读默认使用 DeepSeek，可在服务端独立切换。Owner 控制识别开关，并查看 OCR 页数、ASR 秒数和 TTS 字符用量。部署方在服务端维护 API 凭据。[DeepSeek OCR](https://api-docs.deepseek.com/guides/ocr/) · [DeepSeek ASR](https://api-docs.deepseek.com/guides/asr/)

## 开通

平台运维人员在服务主机运行 `python3 manage_secrets.py set-deepseek`，以交互方式录入加密运维库。部署也支持直接向服务进程注入 `DEEPSEEK_API_KEY`。向现有机构套餐发放识别页数与录音秒数，额度由实际订单决定。调用工具时使用独立的工具端点，无需选择聊天模型。

```bash
python3 manage_plan.py --db .local/workspace.sqlite3 grant --name "机构 AI 套餐" --tokens 100000 --ocr-pages 200 --asr-seconds 3600 --expires 2026-12-31
python3 manage_plan.py --db .local/workspace.sqlite3 status
```

只调整当前套餐的 OCR 页数时，平台运营方可以运行 `python3 manage_plan.py --db .local/workspace.sqlite3 ocr-quota --pages 100`。数字表示本期总页数，已识别页数和在途预留继续计入，语音额度和到期日维持原值。机构端在识别设置中查看当前额度。

自营机构可由平台运营方开通不限累计时长的语音转写。每段录音的处理限制和实际秒数计量依旧适用，该机构续期后继续使用此设置。恢复累计上限时，新的本期秒数须覆盖已用与在途时长。

```bash
python3 manage_plan.py --db .local/workspace.sqlite3 asr-quota --unlimited
python3 manage_plan.py --db .local/workspace.sqlite3 asr-quota --seconds 3600
```

在机构设置中可分别停用 OCR 和 ASR，也可查看语音时长上限、已用和在途数据。新服务期内，按量套餐的识别额度初始为零。两个工具均需启用有效套餐，供应商服务单独结算。模型对话与分析使用独立的 token 额度。

## 切换语音服务

部署方通过服务进程的环境变量设置供应商，修改后重启服务。ASR 与 TTS 可以使用不同服务，也可以通过同一个自建网关分别调用。

| 功能 | 供应商开关 | OpenAI 直连 | OpenAI 兼容服务 |
| --- | --- | --- | --- |
| 语音转写 | `NH_ASR_PROVIDER` | `openai`，`OPENAI_API_KEY`，`NH_ASR_MODEL` 默认 `gpt-transcribe` | `compatible`，填写 `NH_ASR_ENDPOINT` 和 `NH_ASR_MODEL`，需要认证时设置 `NH_ASR_API_KEY` |
| 朗读 | `NH_TTS_PROVIDER` | `openai`，`OPENAI_API_KEY`，显式设置 `NH_TTS_MODEL` | `compatible`，填写 `NH_TTS_ENDPOINT` 和 `NH_TTS_MODEL`，需要认证时设置 `NH_TTS_API_KEY` |

两个开关均可设为 `deepseek`，省略时也使用 DeepSeek。`openai` 和 `compatible` 的朗读音色由 `NH_TTS_VOICE` 指定，默认为 `alloy`。OpenAI 直连朗读使用旧版 `/v1/audio/speech`。其现有模型计划于 2027 年 1 月 6 日停止服务，后继 Realtime 协议需独立适配。[OpenAI 转写接口](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create) · [OpenAI 朗读接口](https://developers.openai.com/api/reference/resources/audio/subresources/speech/methods/create)

`compatible` 接收部署方配置的完整 HTTPS 地址。本机网关可用 `http://127.0.0.1` 或 `http://localhost`，例如 `http://127.0.0.1:8080/v1/audio/transcriptions`。ASR 端点接收 multipart 表单的 `file`、`model` 和 `response_format=json`，返回含 `text` 的 JSON。TTS 端点接收 JSON `model`、`input`、`voice` 和 `response_format=wav`，返回 WAV 音频字节。遇到供应商原生协议时，可在网关转换请求与响应。

OpenAI 与兼容服务的 ASR 按服务端核实的录音时长计量，已有转写回执可继续使用。朗读用量沿用现有字符统计规则。套餐用量与供应商实际计费各自结算。

## 文书原件与人工复核

在长辈档案选择「存档医疗文书」，上传 PDF、JPEG 或 PNG 并选择「DeepSeek OCR」。每份原件上限 8 MiB，PDF 支持 1–1000 页，照片识别上限为 2,000 万像素。选取 PDF 后，机构服务器核实页数，表单显示本次预计使用的 OCR 页数。勾选并确认后，先将完整原件写入加密数据库，再使用通用文件名将整份文书一次发送给 DeepSeek。

服务主机需安装 Poppler 的 `pdfinfo` 和 `pdftoppm`（Debian 或 Ubuntu 的 `poppler-utils`），分别用于核页和逐页生成预览。医疗原件在内存中交给这两个程序。PDF 的原件下载、页面预览都检查医疗查阅权限及分院归属。复核人可按页比对文字、位置框和原件，逐页确认，回填凭证保留具体页码与行号。

`dossier.ocr` 接受 `residentId`、`documentId` 或 `imageHash` 及布尔值 `consent: true`。服务端以本人的医疗写入授权和长辈所在分院核对原件。返回文字及供应商提供的位置框；无位置的文字按原文展示。失败时可以查看原图后手工录入。具备医疗查阅、医疗写入和临床权限的人员核对姓名、原文和待改字段，再签认一次性概括。再次查看、核对或读取已归档的结果均在本地完成。既有档案的原件、识别结果与签署来源继续可读。

## 在任一业务页说话

打开右上角「健康助理」，按住麦克风说话，松开后将本段录音提交机构配置的语音服务。首次使用需在浏览器允许麦克风。在未勾选「语音转写后自动发送」时，可先编辑转写再按 Enter 发送；勾选后转写成功即发送。关闭对话会停止收音。语音只负责转写，工单与通知的发布另有业务审核窗。

已获语音权限的在岗员工可以使用 `POST /api/assistant/voice`。请求发送 WAV 或 Ogg Opus，并通过 `X-DeepSeek-Consent: yes` 记录用户本次操作。房间页发起的对话会同时传递所选区域。语音原件、回执和媒体用量沿用加密存储，账号或区域授权变化后须重新核对。原有独立业务语音接口供旧客户端继续使用。ASR 按音频秒数计量，转写文字发给对话后按模型实际 token 单独结算。[DeepSeek 语音转文字](https://api-docs.deepseek.com/guides/asr/)

## 录音与工单确认

在「预警与人工确认 → 登记语音草稿」选工单，使用麦克风或选择已有录音。浏览器采集需要 HTTPS 或 localhost 及麦克风授权。文件支持 16 位 PCM WAV、Ogg Opus，最多 120 秒和 8 MiB。勾选发送本段录音后，机构服务器移除 WAV 的描述块或 Ogg Opus 的标签注释，再向所配置的 ASR 提交音频和通用文件名。原件在本地加密保存。返回的只读原文旁有可编辑的拟写入记录。若录音中含多人声音，先确认收音范围和使用授权。

| 动作 | 权限与结果 |
| --- | --- |
| `POST /api/media/asr/{taskId}` | 需要 `voice`、`care`、该长辈所属分院，以及当日或逾期的在住长辈待执行工单。请求体为音频原始字节，`X-DeepSeek-Consent: yes`。成功返回 `text`、`durationMs`、`transcriptId`。 |
| `gw.propose` | 护工核对原文和拟写入内容后提交。使用 ASR 时，带上原 `transcriptId` 和原文，服务端核对发起人、工单与文字。原始录音、转写与关联编号保存在加密数据库。 |
| `GET /api/voice-proposals/{id}` | 授权确认人打开具体待办时读取转录与拟写内容；队列仅含任务元数据。完成或退回后，原确认窗口关闭。 |
| `gw.confirm` 或 `gw.dismiss` | 有范围内 `voice.confirm` 和 `care` 权限的人员核对或退回。确认与工单完成共用一个事务，处理后从共同待办移除。 |

## 中断与对账

服务端在发送前预留完整文书的实际页数或向上取整的音频秒数。例如六页 PDF 需要预留六页额度，同一原件再次查阅可复用已存结果。重复提交相同文书复用已保存结果。同一人、同一工单、同一录音复用转写。返回成功后按回执结算，权限变更会在返回给用户前再次检查。OCR 和 ASR 的资料、回执及待核对记录进入机构快照。

连接中断时，服务端可能已经接收文件并计费。系统保留预留额，同一份资料再次点击会提示待核对。平台运营方可按供应商侧实际用量结算；处理中断超过十分钟的未决预留也可核对。对账确认为零用量后可以重新授权发送。已经扣费但缺少返回文本的 PDF 可按留存原件人工核对。

如果人工结算后才收到完整的供应商回执，系统保留原结算状态并计入已确认用量。已确认计费的同一份原件、语音或朗读分段不会重复提交。

```bash
python3 manage_plan.py --db .local/workspace.sqlite3 media-unsettled
python3 manage_plan.py --db .local/workspace.sqlite3 media-reconcile --call CALL_ID --units CONFIRMED_PAGES_OR_SECONDS
```

## 健康助理语音整理

「按住说话」复用机构配置的 ASR 响应，先清理明确的语气词、重复句首和可确认的页面指令改口，再送入对话。整理使用规则处理，每段录音仍只需一次转写请求。姓名、房号、金额、日期、用药和否定表达按转写内容保留，含糊的更正按原话交给经办人核对。开启自动发送时直接发送整理后的版本。可在「查看原话」检查刚刚一段转写，发送前可选择「使用原话」。

## 健康助理朗读

用「按住说话」录音前，可在空白输入区先勾选「朗读」。转写完成后手动发送与自动发送均有效。当前助理面板会保留选择，普通文字提问不会请求音频。服务端核对账号、区域、会话及转写回执，随着文字逐步显示把短句交给朗读服务合成，可提前准备下一段。声纹小窗显示朗读状态，支持暂停、继续和退出。收起助理或退出账号也会停止播放。Owner 可查看已计费和待核对字符。[DeepSeek TTS](https://api-docs.deepseek.com/guides/tts/)
