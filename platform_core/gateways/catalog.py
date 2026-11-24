"""Versioned connector contracts. Adapters are reserved until a provider is configured."""

from copy import deepcopy

# The provider's name, hardware model and available signals must be confirmed at onboarding.
SOURCES = {
    "youle": "优乐模型",
    "radar": "超声波 / 雷达",
    "sensor": "房间传感器",
    "mijia": "米家授权设备",
    "badge": "七有护理工牌",
}

TEXT = {"type": "string", "minLength": 1}
ID = {**TEXT, "maxLength": 160}
DATE = {"type": "string", "format": "date"}
TIME = {"type": "string", "format": "date-time"}
INT = {"type": "integer", "minimum": 0}
NUMBER = {"type": "number"}
BOOL = {"type": "boolean"}


def choice(*items):
    return {"type": "string", "enum": list(items)}


def array(element):
    return {"type": "array", "items": element}


def obj(required, optional=None):
    return {
        "type": "object",
        "required": list(required),
        "properties": {**required, **(optional or {})},
        "additionalProperties": False,
    }


PERIOD = {"from": TIME, "through": TIME}
EVENT = {"deviceId": ID, "eventId": ID, "observedAt": TIME}
SERVICE = {"sessionId": ID, "staffId": ID, "residentId": ID}
JOB = obj(
    {"jobId": ID, "status": choice("queued", "ready", "failed")}, {"artifactId": ID}
)
ACK = obj({"eventId": ID, "accepted": BOOL})
POINT = obj(
    {"at": TIME, "method": choice("gps", "wifi", "cell")},
    {
        "latitude": NUMBER,
        "longitude": NUMBER,
        "floor": TEXT,
        "areaId": ID,
        "accuracyMeters": NUMBER,
    },
)
SEGMENT = obj({"startMs": INT, "endMs": INT, "text": TEXT}, {"speakerRef": ID})
METRICS = obj(
    {
        "staffId": ID,
        "residentCount": INT,
        "serviceSeconds": INT,
        "recordingSeconds": INT,
        "riskCount": INT,
    }
)
RECORD_REF = obj({"recordId": ID, "at": TIME, "type": TEXT}, {"artifactId": ID})
RISK = choice(
    "help",
    "dispute",
    "distress_tone",
    "fall_sound",
    "possible_fall",
    "possible_wandering",
)
INCIDENT = obj(
    {**EVENT, "roomId": ID, "signal": choice("possible_fall", "prolonged_bedrest")},
    {
        "residentHint": ID,
        "evidenceRef": ID,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
)
CONTROL = "正式对接时校验设备或调用者身份、机构归属和数据使用授权。"


def entry(key, group, title, pages, description, request, response, policy=CONTROL):
    return {
        "id": key,
        "group": group,
        "title": title,
        "pages": pages,
        "description": description,
        "method": "POST",
        "path": "/api/integrations/" + key,
        "version": "1.0",
        "status": "reserved",
        "ownerOnly": key == "deepseek-summary",
        "requestSchema": request,
        "responseSchema": response,
        "policy": policy,
    }


BADGE = "工牌与定位"
QUALITY = "质控与通知"
REPORT = "报表与人员"
IOT = "院内设备"
MODEL = "语音与文档"

_CAPABILITIES = [
    entry(
        "badge.telemetry",
        BADGE,
        "工牌状态与硬件遥测",
        [1, 6, 7, 10],
        "登记型号、4G 联网与信号、电量、录音状态、按键、指示灯及充电状态。",
        obj(
            EVENT,
            {
                "model": TEXT,
                "firmware": TEXT,
                "batteryPercent": {"type": "integer", "minimum": 0, "maximum": 100},
                "rssi": NUMBER,
                "online": BOOL,
                "recording": BOOL,
                "charging": BOOL,
                "indicator": choice("blue_pulsing", "blue", "green", "red", "off"),
                "button": choice("power", "record"),
            },
        ),
        ACK,
    ),
    entry(
        "badge.service-session",
        BADGE,
        "服务时段与定向录音",
        [1, 4, 7, 16, 18],
        "绑定工牌、人员和长者的服务时段。保留开始、结束、知情授权与用途标识。",
        obj(
            {**EVENT, **SERVICE, "operation": choice("start", "stop"), "consentRef": ID}
        ),
        ACK,
    ),
    entry(
        "badge.remote-recording",
        BADGE,
        "远程录音控制与回执",
        [5, 10, 16],
        "对已获授权的服务会话下发启停指令，关联操作人与设备回执。",
        obj(
            {
                "deviceId": ID,
                "sessionId": ID,
                "commandId": ID,
                "operation": choice("start", "stop"),
                "purpose": TEXT,
                "consentRef": ID,
            }
        ),
        obj({"commandId": ID, "status": choice("pending", "acknowledged", "rejected")}),
    ),
    entry(
        "badge.audio-chunk",
        BADGE,
        "录音上传与离线补传",
        [1, 4, 6, 16, 21],
        "按会话和分片编号传递对象存储引用、校验值及偏移，支持断网后补传。",
        obj(
            {
                "deviceId": ID,
                "sessionId": ID,
                "chunkIndex": INT,
                "offsetMs": INT,
                "durationMs": INT,
                "audioRef": ID,
                "sha256": {"type": "string", "pattern": "^[a-fA-F0-9]{64}$"},
            }
        ),
        obj({"sessionId": ID, "chunkIndex": INT, "accepted": BOOL}),
        "录音只在授权服务时段采集。传输与存储加密由正式通道实现并验收。",
    ),
    entry(
        "badge.transcription",
        BADGE,
        "普通话与方言转写",
        [1, 4, 12, 20],
        "提交已授权的音频引用，返回含起止位置的转写片段与语言标签。",
        obj({"sessionId": ID, "audioRef": ID, "locale": TEXT}),
        obj({"transcriptId": ID, "segments": array(SEGMENT)}),
    ),
    entry(
        "badge.position",
        BADGE,
        "室内楼层与室外位置上报",
        [6, 10, 11],
        "接收 GPS、基站或 Wi-Fi 报告的位置和定位精度。",
        obj({**EVENT, "staffId": ID, "point": POINT}),
        ACK,
    ),
    entry(
        "badge.track",
        BADGE,
        "人员位置地图与轨迹回放",
        [10, 11],
        "按人员、时段查当前位置、历史路径与停留时间。",
        obj({"staffId": ID, **PERIOD}),
        obj({"points": array(POINT), "stays": array(obj({"areaId": ID, **PERIOD}))}),
    ),
    entry(
        "badge.dashboard",
        QUALITY,
        "分院服务总览",
        [2, 4, 5, 10, 18],
        "按分院汇总服务人数、时长、录音时长、风险数和设备在线情况。",
        obj({"facilityIds": array(ID), **PERIOD}),
        obj(
            {
                "facilities": array(
                    obj(
                        {
                            "facilityId": ID,
                            "onlineDevices": INT,
                            "offlineDevices": INT,
                            "metrics": array(METRICS),
                        }
                    )
                )
            }
        ),
    ),
    entry(
        "badge.risk-detection",
        QUALITY,
        "呼救、争执、语气、跌倒声与走失风险",
        [1, 4, 12, 18, 23],
        "关联音频片段或定位证据，提交待人工核实的风险类型、时间与置信度。",
        obj(
            {**EVENT, "roomId": ID, "risk": RISK, "evidenceRef": ID},
            {"sessionId": ID, "residentHint": ID, "startMs": INT, "endMs": INT},
        ),
        ACK,
    ),
    entry(
        "badge.risk-notification",
        QUALITY,
        "预警弹窗、邮件与处置回执",
        [4, 12, 18],
        "关联事件、渠道、接收角色、送达状态和复核结果，重试保持事件编号一致。",
        obj(
            {
                "alertId": ID,
                "recipientRole": TEXT,
                "channel": choice("dashboard", "email", "approved_family"),
                "deliveryKey": ID,
            }
        ),
        obj({"deliveryId": ID, "state": choice("queued", "delivered", "failed")}),
    ),
    entry(
        "badge.evidence",
        QUALITY,
        "原声证据回放与听取日志",
        [2, 4, 5, 12, 16, 21, 23],
        "按授权用途定位录音片段，生成受限回放凭据与访问日志。覆盖投诉复核和整改培训场景。",
        obj(
            {"sessionId": ID, "purpose": TEXT, "startMs": INT, "endMs": INT},
            {"incidentId": ID},
        ),
        obj({"playbackGrant": ID, "expiresAt": TIME, "auditId": ID}),
        "仅获授权管理者可调阅原声。记录听取人员、使用目的、片段与时间。",
    ),
    entry(
        "badge.service-standards",
        QUALITY,
        "服务用语、流程与质量评价",
        [2, 4, 5, 18, 23],
        "登记机构标准版本，按转写与表扬原声形成过程评分、偏差提醒、整改建议及考核依据。",
        obj(
            {"facilityId": ID, "rulesetId": ID, "transcriptId": ID},
            {"praiseRefs": array(ID)},
        ),
        obj(
            {
                "reviewId": ID,
                "score": NUMBER,
                "deviations": array(TEXT),
                "evidenceRefs": array(ID),
                "trainingSuggestions": array(TEXT),
            }
        ),
    ),
    entry(
        "badge.grade-config",
        REPORT,
        "护理等级、服务配比与分配",
        [14],
        "登记机构自定义护理等级、服务项与人员配比，支持长者到照护标准及护理员的匹配。",
        obj(
            {
                "facilityId": ID,
                "gradeId": ID,
                "name": TEXT,
                "serviceIds": array(ID),
                "staffRatio": TEXT,
            },
            {"residentIds": array(ID)},
        ),
        obj(
            {
                "configVersion": ID,
                "assignments": array(obj({"residentId": ID, "staffId": ID})),
            }
        ),
    ),
    entry(
        "badge.roster-template",
        REPORT,
        "机构批量导入模板",
        [15],
        "领取指定版本的护理员、长者 Excel 表头模板。",
        obj({"rosterType": choice("staff", "resident"), "templateVersion": ID}),
        JOB,
    ),
    entry(
        "badge.roster-import",
        REPORT,
        "人员导入、错误行、账号和工牌绑定",
        [15],
        "校验导入表格，预览错误行。经确认后建立账号、绑定工牌并批量分配服务长者。",
        obj(
            {
                "uploadRef": ID,
                "templateVersion": ID,
                "mode": choice("validate", "commit"),
                "requestId": ID,
            }
        ),
        obj(
            {
                "batchId": ID,
                "errors": array(obj({"row": INT, "column": TEXT, "message": TEXT})),
                "createdCount": INT,
            }
        ),
    ),
    entry(
        "badge.staff-daily",
        REPORT,
        "护理员日报与月度汇总",
        [4, 5, 9, 13, 17, 18, 19],
        "预留定时汇总与人工取件入口，按人统计服务长者数量、服务与录音时长，按时间列风险，可生成 PDF。",
        obj(
            {
                "staffId": ID,
                "date": DATE,
                "period": choice("daily", "monthly"),
                "format": choice("pdf", "json"),
            }
        ),
        JOB,
    ),
    entry(
        "badge.resident-daily",
        REPORT,
        "长者日报、摘要与风险标记",
        [4, 9, 17, 18, 20],
        "按长者汇总服务次数、时长、护理员和用药饮食情绪异常，生成可供授权分享的 PDF。",
        obj({"residentId": ID, "date": DATE, "format": choice("pdf", "json")}),
        JOB,
    ),
    entry(
        "badge.family-delivery",
        REPORT,
        "家属日报与异常通知",
        [4, 9, 17, 18, 20, 23],
        "按亲属授权关系与机构审核记录，将获准的日报或异常提示通过微信等渠道投递。",
        obj(
            {
                "residentId": ID,
                "relativeId": ID,
                "artifactId": ID,
                "approvalId": ID,
                "channel": choice("wechat", "app"),
            }
        ),
        obj({"deliveryId": ID, "status": choice("queued", "delivered", "failed")}),
    ),
    entry(
        "badge.resident-history",
        REPORT,
        "长者历史时间轴与退住导出",
        [9, 17, 18, 21],
        "按人和日期关联服务记录、授权录音、日报。按范围翻页或生成交付档案。",
        obj(
            {"residentId": ID, **PERIOD, "mode": choice("timeline", "export")},
            {"cursor": ID},
        ),
        obj({"items": array(RECORD_REF)}, {"nextCursor": ID, "artifactId": ID}),
    ),
    entry(
        "badge.service-export",
        REPORT,
        "服务明细与计划执行对照 Excel",
        [2, 4, 8, 16, 18, 22],
        "按周、月、自定义日期、长者及护理员筛选时长、风险和计划频次，保留实际时段、未完成、部分完成、计划外服务及人工修订。",
        obj(
            {**PERIOD, "format": choice("xlsx")},
            {"residentId": ID, "staffId": ID, "includeAmendments": BOOL},
        ),
        JOB,
    ),
    entry(
        "badge.access-audit",
        QUALITY,
        "授权、调阅与审计导出",
        [16, 21, 23],
        "关联用途告知、服务时段、访问授权及导出记录，按人员时段查阅。",
        obj(
            {**PERIOD, "facilityId": ID},
            {"actorId": ID, "residentId": ID, "purpose": TEXT},
        ),
        obj(
            {
                "entries": array(
                    obj(
                        {
                            "actorId": ID,
                            "at": TIME,
                            "action": TEXT,
                            "purpose": TEXT,
                            "objectId": ID,
                        }
                    )
                )
            }
        ),
    ),
    entry(
        "iot.youle",
        IOT,
        "优乐模型事件适配",
        [],
        "厂商协议待确认。预留疑似跌倒、持续卧床及证据引用，签名、阈值和推理由接入方确认。",
        INCIDENT,
        ACK,
    ),
    entry(
        "iot.sensor",
        IOT,
        "超声波雷达与人体传感器",
        [],
        "预留在床、离床、活动、距离及观测时长样本，支持设备型号与标定版本。",
        obj(
            {
                **EVENT,
                "roomId": ID,
                "modality": choice("ultrasonic", "radar", "presence", "bed_sensor"),
                "signal": TEXT,
            },
            {"distanceMeters": NUMBER, "durationSeconds": INT, "calibration": TEXT},
        ),
        ACK,
    ),
    entry(
        "iot.mijia-capabilities",
        IOT,
        "米家设备能力清单",
        [],
        "按用户授权、实际型号及实例读取支持的属性、事件和动作，记录能力和授权状态。",
        obj({"authorizationRef": ID, "model": TEXT}),
        obj({"properties": array(ID), "events": array(ID), "actions": array(ID)}),
    ),
    entry(
        "iot.mijia-evidence",
        IOT,
        "米家人体事件、画面或示意图引用",
        [],
        "适配获授权型号实际公开的事件或媒体引用。按能力区分人员存在、图像和疑似跌倒信号。",
        obj(
            {
                **EVENT,
                "model": TEXT,
                "capability": TEXT,
                "roomId": ID,
                "type": choice("presence", "fall_event", "snapshot", "diagram"),
            },
            {"evidenceRef": ID},
        ),
        ACK,
    ),
    entry(
        "voice.transcribe",
        MODEL,
        "语音输入与流式转写",
        [],
        "流式分片及中间文本接口预留。DeepSeek 整段转写已连接 Agent 工作台（POST /api/agent/voice/transcriptions）及护理工单（POST /api/media/asr/{taskId}）。",
        obj(
            {"requestId": ID, "audioRef": ID, "locale": TEXT},
            {"sequence": INT, "isFinal": BOOL},
        ),
        obj({"requestId": ID, "partialText": TEXT, "isFinal": BOOL}),
    ),
    entry(
        "voice.proposal",
        MODEL,
        "语音意图与待确认变更",
        [],
        "模型提出白名单工单变更，传递语音请求、工单编号和变更草稿。正式执行走院内确认命令。",
        obj({"requestId": ID, "transcript": TEXT, "taskId": ID}),
        obj(
            {
                "targetAction": choice("care.completeTask"),
                "patch": obj({"status": choice("已完成"), "note": TEXT}),
            }
        ),
    ),
    entry(
        "document.ocr",
        MODEL,
        "医学文档 OCR",
        [],
        "工牌外部适配端口预留。长者档案已通过 dossier.ocr 接入 DeepSeek，原件和转录供人工核对。",
        obj({"documentId": ID, "requestId": ID, "imageRef": ID}),
        obj({"text": TEXT, "pages": array(obj({"page": INT, "text": TEXT}))}),
    ),
    entry(
        "deepseek-summary",
        MODEL,
        "DeepSeek 病历概括",
        [],
        "预留从原文事实生成一次文档概括的调用，账号配置由业主管理。",
        obj({"documentId": ID, "requestId": ID, "sourceText": TEXT}),
        obj({"source": TEXT, "facts": array(TEXT), "pendingReview": array(TEXT)}),
    ),
]


def catalog():
    return deepcopy(_CAPABILITIES)
