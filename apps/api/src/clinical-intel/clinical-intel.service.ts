import { Injectable, NotFoundException, OnModuleInit } from '@nestjs/common';
import { PrismaService } from '../prisma/prisma.service';
import { BUILTIN_PROMPTS } from './prompts';

/**
 * 临床智能预留层：声学异常 → 档案更新 → AI 预诊 → 院内推送（家属需人工确认）。
 * 实际 SOTA 推理通过 AcousticSensitivityConfig.inferenceBaseUrl 接入；空则 stub。
 */
@Injectable()
export class ClinicalIntelService implements OnModuleInit {
  constructor(private prisma: PrismaService) {}

  async onModuleInit() {
    const tenant = await this.prisma.tenant.findFirst();
    if (tenant) await this.ensureDefaults(tenant.id);
  }

  async ensureDefaults(tenantId: string) {
    await this.prisma.acousticSensitivityConfig.upsert({
      where: { tenantId_name: { tenantId, name: 'default' } },
      create: { tenantId, name: 'default' },
      update: {},
    });
    for (const p of BUILTIN_PROMPTS) {
      await this.prisma.promptTemplate.upsert({
        where: { tenantId_key_version: { tenantId, key: p.key, version: p.version } },
        create: { tenantId, key: p.key, title: p.title, version: p.version, content: p.content },
        update: {},
      });
    }
  }

  // ——— 敏捷度设置 ———
  getConfig(tenantId: string, name = 'default') {
    return this.prisma.acousticSensitivityConfig.findUnique({
      where: { tenantId_name: { tenantId, name } },
    });
  }

  async upsertConfig(tenantId: string, data: any) {
    const name = data.name || 'default';
    return this.prisma.acousticSensitivityConfig.upsert({
      where: { tenantId_name: { tenantId, name } },
      create: { tenantId, name, ...this.pickConfig(data) },
      update: this.pickConfig(data),
    });
  }

  private pickConfig(data: any) {
    const keys = [
      'coughSensitivity',
      'paroxysmalWindowSec',
      'paroxysmalMinCount',
      'hardImpactThreshold',
      'softImpactIgnore',
      'contextBoost',
      'autoUpdateProfile',
      'autoFacilityPush',
      'inferenceBaseUrl',
      'inferenceApiKey',
      'modelId',
      'enabled',
    ] as const;
    const out: Record<string, unknown> = {};
    for (const k of keys) if (data[k] !== undefined) out[k] = data[k];
    return out;
  }

  // ——— 设备 ———
  listDevices(tenantId: string) {
    return this.prisma.acousticDevice.findMany({ where: { tenantId }, orderBy: { code: 'asc' } });
  }

  upsertDevice(tenantId: string, data: any) {
    return this.prisma.acousticDevice.upsert({
      where: { tenantId_code: { tenantId, code: data.code } },
      create: {
        tenantId,
        code: data.code,
        name: data.name || data.code,
        bedId: data.bedId,
        elderId: data.elderId,
        vendor: data.vendor || 'generic',
        enabled: data.enabled !== false,
        metaJson: data.metaJson ? JSON.stringify(data.metaJson) : null,
      },
      update: {
        name: data.name,
        bedId: data.bedId,
        elderId: data.elderId,
        vendor: data.vendor,
        enabled: data.enabled,
        metaJson: data.metaJson != null ? JSON.stringify(data.metaJson) : undefined,
      },
    });
  }

  // ——— 提示词 ———
  listPrompts(tenantId: string) {
    return this.prisma.promptTemplate.findMany({
      where: { tenantId, enabled: true },
      orderBy: [{ key: 'asc' }, { version: 'desc' }],
    });
  }

  async upsertPrompt(tenantId: string, data: any) {
    return this.prisma.promptTemplate.upsert({
      where: {
        tenantId_key_version: {
          tenantId,
          key: data.key,
          version: data.version || 'v1',
        },
      },
      create: {
        tenantId,
        key: data.key,
        title: data.title || data.key,
        content: data.content,
        version: data.version || 'v1',
        locale: data.locale || 'zh-CN',
        enabled: data.enabled !== false,
      },
      update: {
        title: data.title,
        content: data.content,
        locale: data.locale,
        enabled: data.enabled,
      },
    });
  }

  // ——— 声学事件摄入（接口预留：可接麦克风网关 / Agent / SOTA） ———
  async ingestEvent(tenantId: string, body: any) {
    const cfg = (await this.getConfig(tenantId)) || (await this.upsertConfig(tenantId, {}));
    if (!cfg.enabled) {
      return { accepted: false, reason: 'acoustic pipeline disabled' };
    }

    let classified = await this.callInferenceOrStub(cfg, body);
    const event = await this.prisma.acousticEvent.create({
      data: {
        tenantId,
        elderId: body.elderId || body.elder_id,
        deviceId: body.deviceId || body.device_id,
        bedId: body.bedId || body.bed_id,
        eventType: classified.eventType,
        subtype: classified.subtype,
        confidence: classified.confidence,
        severity: classified.severity,
        pathological: classified.pathological,
        contextScore: classified.contextScore,
        modelId: classified.modelId,
        modelVersion: classified.modelVersion,
        rawJson: body.features ? JSON.stringify(body.features) : body.rawJson,
        audioUri: body.audioUri || body.audio_uri,
        decidedBy: classified.decidedBy,
        status: classified.pathological ? 'accepted' : 'pending',
        note: classified.note,
      },
    });

    let finding: any = null;
    let profile: any = null;
    let push: any = null;

    if (classified.pathological && event.elderId) {
      if (cfg.autoUpdateProfile) {
        finding = await this.writeFinding(tenantId, event, classified);
        profile = await this.syncElderProfile(event.elderId, finding);
      }
      if (cfg.autoFacilityPush) {
        push = await this.queueFacilityPush(tenantId, event.elderId, event.id, classified);
      }
    }

    return {
      accepted: true,
      event,
      classification: classified,
      finding,
      profileUpdated: !!profile,
      facilityPush: push,
      integration: {
        stub: !cfg.inferenceBaseUrl,
        docs: '/docs/clinical-intel-sota.md',
        next: 'POST /api/clinical/prediagnosis/generate',
      },
    };
  }

  /** SOTA 接入点：有 URL 则转发；否则本地规则 stub */
  private async callInferenceOrStub(cfg: any, body: any) {
    if (cfg.inferenceBaseUrl) {
      try {
        const res = await fetch(`${cfg.inferenceBaseUrl.replace(/\/$/, '')}/v1/acoustic/classify`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(cfg.inferenceApiKey ? { Authorization: `Bearer ${cfg.inferenceApiKey}` } : {}),
          },
          body: JSON.stringify({
            ...body,
            sensitivity: {
              coughSensitivity: cfg.coughSensitivity,
              paroxysmalWindowSec: cfg.paroxysmalWindowSec,
              paroxysmalMinCount: cfg.paroxysmalMinCount,
              hardImpactThreshold: cfg.hardImpactThreshold,
              softImpactIgnore: cfg.softImpactIgnore,
              contextBoost: cfg.contextBoost,
            },
          }),
        });
        if (res.ok) {
          const data = await res.json();
          return {
            eventType: data.event_type || data.eventType || 'unknown',
            subtype: data.subtype,
            confidence: Number(data.confidence ?? 0),
            severity: data.severity || 'low',
            pathological: !!data.pathological,
            contextScore: data.context_score ?? data.contextScore,
            modelId: data.model_id || cfg.modelId,
            modelVersion: data.model_version || 'remote',
            decidedBy: 'sota',
            note: data.note || 'remote sota classification',
          };
        }
      } catch {
        /* fall through to stub */
      }
    }
    return this.stubClassify(cfg, body);
  }

  /**
   * Stub 分类器：演示规则，非生产模型。
   * - 急促咳嗽 / 硬碰撞 → pathological
   * - 软碰撞 → 忽略
   */
  private stubClassify(cfg: any, body: any) {
    const hint = String(body.hint || body.eventType || body.event_type || '').toLowerCase();
    const conf = Number(body.confidence ?? 0.6);
    let eventType = 'unknown';
    let subtype: string | null = null;
    let pathological = false;
    let severity = 'low';
    let note = 'stub rule';

    if (hint.includes('cough') || hint.includes('咳嗽')) {
      eventType = 'cough';
      const paroxysmal = !!body.paroxysmal || hint.includes('急促') || hint.includes('paroxysmal') || conf >= cfg.coughSensitivity + 0.15;
      subtype = paroxysmal ? 'paroxysmal_cough' : 'mild_cough';
      pathological = paroxysmal && conf >= cfg.coughSensitivity;
      severity = pathological ? 'high' : 'low';
      note = pathological ? '突发急促型咳嗽（stub）' : '普通咳嗽，未达病理阈值（stub）';
    } else if (hint.includes('impact') || hint.includes('碰撞') || hint.includes('撞击')) {
      eventType = 'impact';
      const hard = !!body.hard || conf >= cfg.hardImpactThreshold || hint.includes('硬') || hint.includes('明显');
      subtype = hard ? 'hard_impact' : 'soft_impact';
      if (!hard && cfg.softImpactIgnore) {
        pathological = false;
        severity = 'low';
        note = '普通碰撞异响，默认忽略（stub）';
      } else {
        pathological = hard;
        severity = hard ? 'critical' : 'low';
        note = hard ? '明显碰撞异响，建议床旁查看（stub）' : '软碰撞';
      }
    } else if (body.features || body.audioUri) {
      eventType = body.eventType || 'unknown';
      pathological = false;
      note = '已接收特征/音频 URI，等待 SOTA 模型接入';
    }

    const contextScore = Math.min(1, conf + (pathological ? cfg.contextBoost : 0));
    return {
      eventType,
      subtype,
      confidence: conf,
      severity,
      pathological,
      contextScore,
      modelId: cfg.modelId || 'stub-acoustic-v0',
      modelVersion: 'stub',
      decidedBy: 'stub',
      note,
    };
  }

  private async writeFinding(tenantId: string, event: any, classified: any) {
    const title =
      classified.subtype === 'paroxysmal_cough'
        ? '急促型咳嗽发作'
        : classified.subtype === 'hard_impact'
          ? '明显碰撞异响'
          : classified.note || '声学异常';
    return this.prisma.clinicalFinding.create({
      data: {
        tenantId,
        elderId: event.elderId,
        eventId: event.id,
        category: event.eventType === 'cough' ? 'respiratory' : event.eventType === 'impact' ? 'trauma_risk' : 'other',
        code: classified.subtype,
        title,
        detail: classified.note,
        evidenceJson: JSON.stringify({
          confidence: classified.confidence,
          contextScore: classified.contextScore,
          modelId: classified.modelId,
        }),
        source: 'acoustic',
        confidence: classified.confidence,
      },
    });
  }

  private async syncElderProfile(elderId: string, finding: any) {
    const health = await this.prisma.elderHealth.findUnique({ where: { elderId } });
    const tag = finding.code || finding.title;
    const prevTags = health?.acousticRiskTags ? String(health.acousticRiskTags).split(',').filter(Boolean) : [];
    if (!prevTags.includes(tag)) prevTags.push(tag);
    const noteLine = `[${new Date().toISOString().slice(0, 16)}] ${finding.title}: ${finding.detail || ''}`;
    const clinicalNotes = [health?.clinicalNotes, noteLine].filter(Boolean).join('\n').slice(-4000);
    if (health) {
      return this.prisma.elderHealth.update({
        where: { elderId },
        data: { clinicalNotes, acousticRiskTags: prevTags.join(',') },
      });
    }
    return this.prisma.elderHealth.create({
      data: { elderId, clinicalNotes, acousticRiskTags: prevTags.join(',') },
    });
  }

  private async queueFacilityPush(tenantId: string, elderId: string, eventId: string, classified: any) {
    const elder = await this.prisma.elder.findFirst({ where: { id: elderId, tenantId } });
    const title = `院内提醒：${classified.note || classified.subtype || '声学异常'}`;
    const body = `老人 ${elder?.name || elderId} 触发 ${classified.eventType}/${classified.subtype || '-'}，置信度 ${classified.confidence}。请护工复核后再决定是否推送家属。`;
    await this.prisma.alert.create({
      data: {
        tenantId,
        type: 'clinical_acoustic',
        title,
        message: body,
        elderId,
        source: 'clinical-intel',
        severity: classified.severity === 'critical' ? 'high' : 'medium',
        status: 'open',
      },
    });
    return this.prisma.clinicalPush.create({
      data: {
        tenantId,
        elderId,
        eventId,
        audience: 'facility',
        channel: 'in_app',
        title,
        body,
        status: 'sent',
        sentAt: new Date(),
      },
    });
  }

  listEvents(tenantId: string, elderId?: string) {
    return this.prisma.acousticEvent.findMany({
      where: { tenantId, ...(elderId ? { elderId } : {}) },
      orderBy: { createdAt: 'desc' },
      take: 100,
    });
  }

  listFindings(tenantId: string, elderId: string) {
    return this.prisma.clinicalFinding.findMany({
      where: { tenantId, elderId, active: true },
      orderBy: { createdAt: 'desc' },
    });
  }

  // ——— AI 预诊 ———
  async generatePrediagnosis(tenantId: string, elderId: string, opts: { modelId?: string; generatedBy?: string } = {}) {
    const elder = await this.prisma.elder.findFirst({
      where: { id: elderId, tenantId },
      include: { health: true },
    });
    if (!elder) throw new NotFoundException('老人不存在');

    const [findings, events, vitals, prompt] = await Promise.all([
      this.prisma.clinicalFinding.findMany({ where: { elderId, active: true }, take: 20, orderBy: { createdAt: 'desc' } }),
      this.prisma.acousticEvent.findMany({ where: { elderId }, take: 20, orderBy: { createdAt: 'desc' } }),
      this.prisma.vitalSign.findMany({ where: { elderId }, take: 10, orderBy: { recordedAt: 'desc' } }).catch(() => []),
      this.prisma.promptTemplate.findFirst({
        where: { tenantId, key: 'clinical.prediagnosis.v1', enabled: true },
        orderBy: { version: 'desc' },
      }),
    ]);

    const riskPrompt = await this.prisma.promptTemplate.findFirst({
      where: { tenantId, key: 'clinical.risk_hints.v1', enabled: true },
    });

    const draft = this.buildStubPrediagnosis(elder, findings, events, vitals, riskPrompt?.content);

    const report = await this.prisma.prediagnosisReport.create({
      data: {
        tenantId,
        elderId,
        promptKey: prompt?.key || 'clinical.prediagnosis.v1',
        status: 'draft',
        situation: draft.situation,
        medicalAdvice: draft.medicalAdvice,
        riskHints: draft.riskHints,
        inferenceJson: JSON.stringify(draft.inferences),
        modelId: opts.modelId || 'stub-prediagnosis-v0',
        modelVersion: 'stub',
        generatedBy: opts.generatedBy || 'system',
      },
    });

    // 自动更新档案摘要（可追溯）
    const line = `[预诊 ${report.id.slice(-6)}] ${draft.situation.slice(0, 120)}`;
    const clinicalNotes = [elder.health?.clinicalNotes, line].filter(Boolean).join('\n').slice(-4000);
    if (elder.health) {
      await this.prisma.elderHealth.update({ where: { elderId }, data: { clinicalNotes } });
    } else {
      await this.prisma.elderHealth.create({ data: { elderId, clinicalNotes } });
    }

    let facilityPush: any = null;
    if (draft.facilityAlert) {
      facilityPush = await this.prisma.clinicalPush.create({
        data: {
          tenantId,
          elderId,
          reportId: report.id,
          audience: 'facility',
          channel: 'in_app',
          title: `AI 预诊草稿 · ${elder.name}`,
          body: draft.riskHints.slice(0, 500),
          status: 'sent',
          sentAt: new Date(),
        },
      });
      await this.prisma.alert.create({
        data: {
          tenantId,
          type: 'clinical_prediagnosis',
          title: `AI 预诊 · ${elder.name}`,
          message: draft.medicalAdvice.slice(0, 400),
          elderId,
          source: 'clinical-intel',
          severity: 'medium',
        },
      });
    }

    return {
      report,
      draft,
      promptUsed: prompt?.key,
      facilityPush,
      familyPush: {
        status: 'blocked_until_staff_approval',
        recommended: draft.familyPushRecommended,
        approveApi: `POST /api/clinical/pushes/:id/approve-family`,
      },
      disclaimer: '本输出为辅助信息，不构成医疗诊断或处方。',
    };
  }

  private buildStubPrediagnosis(elder: any, findings: any[], events: any[], vitals: any[], riskHintsTpl?: string | null) {
    const findingTitles = findings.map((f) => f.title).join('；') || '暂无结构化病理性特征';
    const recentEvents = events
      .slice(0, 5)
      .map((e) => `${e.createdAt?.toISOString?.()?.slice(0, 16) || ''} ${e.eventType}/${e.subtype || '-'} conf=${e.confidence}`)
      .join('\n');
    const vitalLine = vitals
      .slice(0, 3)
      .map((v: any) => `T=${v.temperature ?? '-'} SpO2=${v.spo2 ?? '-'} BP=${v.systolic ?? '-'}/${v.diastolic ?? '-'}`)
      .join('；');

    const situation = [
      `老人：${elder.name}，护理等级 ${elder.careLevel}，状态 ${elder.status}。`,
      `慢病/过敏：${elder.health?.chronicDiseases || '未登记'} / ${elder.health?.allergies || '未登记'}。`,
      `档案临床摘要：${elder.health?.clinicalNotes || '无'}。`,
      `近期病理性特征：${findingTitles}。`,
      `近期声学事件：\n${recentEvents || '无'}`,
      `近期体征：${vitalLine || '无'}。`,
    ].join('\n');

    const hasCough = findings.some((f) => f.category === 'respiratory') || events.some((e) => e.eventType === 'cough' && e.pathological);
    const hasImpact = findings.some((f) => f.category === 'trauma_risk') || events.some((e) => e.subtype === 'hard_impact');

    const inferences = [] as Array<{ hypothesis: string; confidence: number; rationale: string }>;
    if (hasCough) {
      inferences.push({
        hypothesis: '急性呼吸道刺激或感染相关咳嗽加重（可能性）',
        confidence: 0.45,
        rationale: '急促型咳嗽事件 + 基线慢病上下文（stub 推断）',
      });
      inferences.push({
        hypothesis: '心衰/容量负荷相关夜间咳嗽（可能性）',
        confidence: 0.28,
        rationale: '需结合水肿、夜间端坐呼吸等院内观察，当前证据不足',
      });
    }
    if (hasImpact) {
      inferences.push({
        hypothesis: '床旁碰撞或未遂跌倒（可能性）',
        confidence: 0.55,
        rationale: '硬碰撞异响超阈值，需排除坠床与外伤',
      });
    }
    if (!inferences.length) {
      inferences.push({
        hypothesis: '暂无足够声学/临床证据支持特定推断',
        confidence: 0.2,
        rationale: '事件未达病理阈值或样本不足',
      });
    }

    const medicalAdvice = [
      '1. 护工尽快床旁查看：呼吸频率、意识、皮肤完整性、主诉。',
      hasCough ? '2. 监测血氧与体温；若出现呼吸困难、发绀或持续发热，立即通知值班医护。' : '2. 按护理等级继续常规巡视。',
      hasImpact ? '3. 评估是否坠床/撞击，检查头颈部与四肢，必要时按跌倒应急流程。' : '3. 无需按跌倒流程升级（当前无硬碰撞病理事件）。',
      '4. 本建议为 AI 辅助草稿，须医护复核后方可调整照护计划。',
    ].join('\n');

    const riskHints = [
      riskHintsTpl ? '（已加载系统风险提示词）' : '',
      hasCough ? '【呼吸风险】急促咳嗽可能提示下呼吸道问题，注意血氧与精神状态变化。' : '',
      hasImpact ? '【外伤/跌倒风险】明显碰撞异响，优先排除坠床；普通软碰撞已策略性忽略。' : '',
      '【合规】不向家属发送未经护工批准的推断性诊断名称。',
    ]
      .filter(Boolean)
      .join('\n');

    return {
      situation,
      medicalAdvice,
      riskHints,
      inferences,
      facilityAlert: hasCough || hasImpact,
      familyPushRecommended: hasImpact || (hasCough && findings.length >= 2),
    };
  }

  listReports(tenantId: string, elderId?: string) {
    return this.prisma.prediagnosisReport.findMany({
      where: { tenantId, ...(elderId ? { elderId } : {}) },
      orderBy: { createdAt: 'desc' },
      take: 50,
    });
  }

  getReport(tenantId: string, id: string) {
    return this.prisma.prediagnosisReport.findFirst({ where: { id, tenantId } });
  }

  // ——— 推送审批 ———
  listPushes(tenantId: string, audience?: string) {
    return this.prisma.clinicalPush.findMany({
      where: { tenantId, ...(audience ? { audience } : {}) },
      orderBy: { createdAt: 'desc' },
      take: 80,
    });
  }

  async approveFamilyPush(tenantId: string, pushIdOrReportId: string, staffId: string, body: any = {}) {
    let push = await this.prisma.clinicalPush.findFirst({
      where: { id: pushIdOrReportId, tenantId },
    });
    if (!push && body.reportId) {
      const report = await this.prisma.prediagnosisReport.findFirst({ where: { id: body.reportId, tenantId } });
      if (!report) throw new NotFoundException('报告不存在');
      const familyTpl = await this.prisma.promptTemplate.findFirst({
        where: { tenantId, key: 'clinical.family_push.v1' },
      });
      push = await this.prisma.clinicalPush.create({
        data: {
          tenantId,
          elderId: report.elderId,
          reportId: report.id,
          audience: 'family',
          channel: body.channel || 'wechat',
          title: body.title || '院方健康关注通知',
          body:
            body.body ||
            `${familyTpl ? '【按家属推送规范】' : ''}老人近期出现需关注的情况，院方已介入护理观察。如需了解详情请联系护理站。`,
          status: 'queued',
        },
      });
    }
    if (!push) throw new NotFoundException('推送记录不存在');
    if (push.audience !== 'family') {
      // 基于院内推送克隆家属推送
      push = await this.prisma.clinicalPush.create({
        data: {
          tenantId,
          elderId: push.elderId,
          reportId: push.reportId,
          eventId: push.eventId,
          audience: 'family',
          channel: body.channel || 'wechat',
          title: body.title || push.title.replace('院内', '家属'),
          body: body.body || `院方已关注：${push.body}`,
          status: 'queued',
        },
      });
    }
    return this.prisma.clinicalPush.update({
      where: { id: push.id },
      data: {
        status: 'approved',
        approvedBy: staffId,
        approvedAt: new Date(),
        sentAt: new Date(),
        // 真实短信/微信通道预留：此处标记 approved；渠道适配器后续实现
      },
    });
  }

  async rejectFamilyPush(tenantId: string, id: string, staffId: string, reason?: string) {
    const push = await this.prisma.clinicalPush.findFirst({ where: { id, tenantId } });
    if (!push) throw new NotFoundException();
    return this.prisma.clinicalPush.update({
      where: { id },
      data: { status: 'rejected', approvedBy: staffId, approvedAt: new Date(), error: reason || 'staff rejected' },
    });
  }

  // ——— 学习反馈（对接 extensions / agent） ———
  async markEventNoise(tenantId: string, eventId: string, kind: 'false_positive' | 'false_negative' | 'true_positive', note?: string) {
    const event = await this.prisma.acousticEvent.findFirst({ where: { id: eventId, tenantId } });
    if (!event) throw new NotFoundException();
    const status = kind === 'false_positive' ? 'noise' : kind === 'true_positive' ? 'accepted' : 'pending';
    const updated = await this.prisma.acousticEvent.update({
      where: { id: eventId },
      data: { status, note: note || event.note, decidedBy: 'human' },
    });
    return {
      event: updated,
      learningHint: {
        kind,
        source: 'clinical_acoustic',
        forwardTo: 'POST /api/extensions/learning/correct',
        agentFeedback: 'POST /api/agent/feedback',
      },
    };
  }

  /** 契约说明：给外部 SOTA / 麦克风网关 */
  contract() {
    return {
      module: 'clinical-intel',
      status: 'interfaces_reserved',
      version: '0.1.0',
      docs: 'docs/clinical-intel-sota.md',
      endpoints: {
        config: 'GET/PUT /api/clinical/config',
        devices: 'GET/PUT /api/clinical/devices',
        ingest: 'POST /api/clinical/events/ingest',
        events: 'GET /api/clinical/events',
        findings: 'GET /api/clinical/findings?elderId=',
        prediagnosis: 'POST /api/clinical/prediagnosis/generate',
        reports: 'GET /api/clinical/prediagnosis',
        pushes: 'GET /api/clinical/pushes',
        approveFamily: 'POST /api/clinical/pushes/:id/approve-family',
        rejectFamily: 'POST /api/clinical/pushes/:id/reject-family',
        prompts: 'GET/PUT /api/clinical/prompts',
        labelNoise: 'POST /api/clinical/events/:id/label',
      },
      sota: {
        classifyPath: '/v1/acoustic/classify',
        configureVia: 'AcousticSensitivityConfig.inferenceBaseUrl',
      },
      pushPolicy: 'facility_first_family_requires_staff_approval',
    };
  }
}
