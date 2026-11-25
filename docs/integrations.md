# 机构设备、护理工牌与人工确认接口

## 当前可以验证的流程

**房间预警。** 有模拟接入权限的人员在「预警与人工确认」提交定位、信号、来源和源事件编号，可以补充观测描述、截图或示意图的证据编号。重传相同报文沿用原观测。同一编号对应不同内容会提示核对。

当两个不同来源在首条信号前后 90 秒内报告同一种事件，床位、当时的房间分配、长辈提示均一致，且首条仍待核实时，护士只收到一项待办。详情保留每个来源的观测时间、证据编号和摘要。疑似跌倒排在持续卧床提醒之前。护士的结论同时关联每份观测，只追加一份已核实的长辈档案。复核后再来的新观测单独处理。90 秒是院内试点初值，需用机构实际信号校验。

**护士核实。** 系统在接收时固定房间和在住候选长辈。一间双人房只产生一条待复核预警。护士查看现场资料，选定实际涉及的长辈并填写处置记录，系统将护士、事件时间、房间、证据关联和结果追加到该长辈的历史档案。误报和无法核实留在预警台账。后续转床或退住保留原房间和人员关联。定位错误、房间为空或实际涉及其他房间时，可先记录无法核实，再由授权人员核对档案。接入延迟引起的历史床位匹配需要在设备联调时补充带时间戳的分配记录。

**语音草案。** 护工选择待执行的工单，录音或上传音频后确认使用 DeepSeek 转写，核对拟写入记录。也可直接填写文字。提交后，同一机构内拥有语音确认和工单执行权限的工作人员可看到待办。确认窗显示长辈、房间、原始转写、工单编号、原记录、拟写入内容和执行人。草稿当前支持将一笔照护工单登记为完成。服务器从保存的草稿读取目标与内容，以当前登录账号登记实际执行人。如床位分配、服务对象或工单状态发生变化，确认会被拒绝，待办可退回。确认和工单写入共用事务，此后其他护工查询待办时已看不到这份申请。

**追溯。** 「操作日志」按岗位授权提供查询。发生房间取生成信号或申请时的房间，确认人与发起人分别留痕。结合房间与操作者可查询同一护工在指定房间的操作。上线外部设备后还需保留厂商流水、同意范围、凭证有效期和正式调阅权限。真实录音、音频转写、视频提取、自动告警投递和外部推理均为待接入能力。

## 调用约定

| 入口 | 用法 |
| --- | --- |
| `GET /api/integrations` | 已登录且有目录权限的账号获得 `capabilities` 数组。每项列明编号、分组、业务目的、PDF 物理页码、版本、权限条件、请求与响应 JSON Schema。DeepSeek 端口仅总管理员可见。 |
| `GET /api/integrations/{id}` | 读取单项实现契约及预留状态。 |
| `POST /api/integrations/{id}` | 已登记并有权访问的预留端口返回 HTTP 501 及 `status: not_connected`。契约中的 `responseSchema` 描述未来连接提供方后的成功响应。 |
| `POST /api/commands` | 内部模拟及人工复核使用 `action`、`payload`、`revision`。请提供登录凭据与当前数据版本。版本过期时重新读取工作台，核对后提交。 |

| 已接通的本地动作 | 主要字段 | 所需权限 |
| --- | --- | --- |
| `gw.ingest` | `source`（youle、radar、sensor、mijia、badge）、`eventId`、`bedId`、`signal`（possible_fall 或 prolonged_bedrest）。可选带时区 `observedAt`、`residentId` 线索、`evidenceRef`、`observation`。床位用来定位房间。 | 模拟设备事件 |
| `gw.review` | `alertId`、`decision`、`note`。已核实结论必须指定房间记录中的 `residentId`。 | 预警复核 |
| `gw.propose` | `requestId`、`taskId`、`transcript`、`note`。同一发起人的同一请求号可重试。一张工单同时最多一个待确认申请。 | 发起语音变更和工单执行 |
| `gw.confirm` | `proposalId`。作用目标通过服务端已固定的申请解析。 | 确认语音变更和工单执行 |
| `gw.dismiss` | `proposalId`、`reason`。保留退回原因。 | 确认语音变更和工单执行 |

示例报文中的 `b001` 属于演示库，版本值需从本次会话取得。

```json
{
  "action": "gw.ingest",
  "revision": 0,
  "payload": {
    "source": "radar",
    "eventId": "demo-room-radar-001:42",
    "bedId": "b001",
    "signal": "possible_fall",
    "evidenceRef": "demo-diagram-42",
    "observation": "房间内目标接近地面，人员身份待现场核实。"
  }
}
```

## 《七有 AI 护理工牌 · 机构版》接口映射

页码从 PDF 封面计数。以下能力按产品介绍提取为机构侧接口。硬件重量、续航、实时性和满意度等材料指标供选型或试点实测。

| PDF 页 | 功能与对应端口 |
| --- | --- |
| 1–3 | 产品定位、记录真实性、监管和证据背景。设备状态、服务会话、转写、风险与调阅分别映射到 `badge.telemetry`、`badge.service-session`、`badge.transcription`、`badge.risk-detection`、`badge.evidence`。第 3 页为背景材料。 |
| 4–5 | 定向录音、4G 上传、离线补传、方言转写、异常语气、呼救争执、表扬原声、标准流程评分、原声回放、整改培训、多分院查看与家属日报。参见 `badge.audio-chunk`、`badge.transcription`、`badge.service-standards`、`badge.risk-detection`、`badge.dashboard`、`badge.family-delivery`、`badge.evidence`。 |
| 6–7 | 设备型号、电量、充电、信号、双按键、灯态及录音状态使用 `badge.telemetry`。GPS、基站和室内 Wi-Fi 楼层位置使用 `badge.position`。双麦降噪、尺寸、充电座、防护等级属于硬件验收项。 |
| 8–9 | 按周、月、自定义时间段及护理员、长辈筛选服务时长、录音时长和风险明细，生成 Excel，见 `badge.service-export`。第 9 页阐述家属体验目标。 |
| 10–11 | 实时设备状态、护理员位置地图、服务时长与风险汇总、远程录音控制、历史轨迹和停留时长。对应 `badge.telemetry`、`badge.position`、`badge.dashboard`、`badge.remote-recording`、`badge.track`。 |
| 12 | 呼救、争执、跌倒声的待核实事件，弹窗和邮件送达，录音片段回溯及闭环处理。对应 `badge.risk-detection`、`badge.risk-notification`、`badge.evidence`。 |
| 13–15 | 护理员每日 PDF、月汇总、机构护理等级和服务配比、护理员匹配、Excel 模板、错误行预览、导入、账号工牌绑定及批量分配。对应 `badge.staff-daily`、`badge.grade-config`、`badge.roster-template`、`badge.roster-import`。 |
| 16–18 | 授权服务时段、传输与存储加密、管理员原声调阅、访问日志和导出，用 `badge.service-session`、`badge.audio-chunk`、`badge.evidence`、`badge.access-audit` 表达。家属异常通知、走失线索、服务质量与工作量关联 `badge.family-delivery`、`badge.risk-detection`、`badge.staff-daily`。第 17 页重复家属体验目标。 |
| 19–20 | 护理员日报、按长辈归集的服务次数、时长、人员、用药饮食情绪摘要、异常标记、PDF 与微信交付。对应 `badge.staff-daily`、`badge.resident-daily`、`badge.family-delivery`。 |
| 21–23 | 长辈跨月时间轴、录音与日报调阅、退住时完整导出，以及计划与实际、部分完成、计划外及人工修订的服务明细。对应 `badge.resident-history`、`badge.evidence`、`badge.service-export`、`badge.access-audit`。第 23 页为产品总结。 |

## 米家、雷达与模型接入

1. **先查实际型号。** 小米官方 Home Assistant 集成通过小米账号 OAuth 2.0 授权，按 MIoT 设备服务描述映射属性和事件。实施时先选定型号、固件、区域与网关，检查授权后实际出现的人体存在、运动或厂商跌倒事件。将结果落入 `iot.mijia-capabilities`，逐台绑定院区与房间。仅有“人体存在”时，保留该观测的原始含义。[小米官方集成说明](https://github.com/XiaoMi/ha_xiaomi_home)
2. **媒体单独验收。** 小米说明其官方 Home Assistant 集成无法与摄像机协商 P2P 加密视频密钥，因而无法读取这类实时流。若具体设备通过厂商正式接口提供授权快照或跌倒示意图，可通过 `iot.mijia-evidence` 传递具有权限控制的证据引用。需要厂商说明样例报文、授权范围、有效期和取证限制。[官方摄像机视频流说明](https://github.com/XiaoMi/ha_xiaomi_home/wiki/Features-that-will-not-be-implemented#camera-video-stream)
3. **接入专业设备。** `iot.sensor` 接收超声波、雷达、人体存在或床位传感器观测。`iot.youle` 接收优乐侧的疑似跌倒、持续卧床和证据引用，待厂商确认“优乐”的具体产品、签名方式、时间戳、坐标系、阈值单位与稳定事件编号。首稿的本地模拟流程可验证重复消息、双人房、误报和人工复核。
4. **接入语音和 OCR。** `voice.transcribe` 预留音频分片、部分和最终转写。`voice.proposal` 预留意图草案。`document.ocr` 和 `deepseek-summary` 预留留档图像的识别和一次概括。工牌的流式、分片适配端口预留。桌面实际使用 DeepSeek 官方整段 ASR 与医疗文书 OCR，开通方式和请求协议见[识别工具](media.md)。验收应覆盖断网重传、授权撤回、人工确认、处理过的申请在其他账号消失、跨房间查询与原图留存。
