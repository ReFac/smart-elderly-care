import { ForbiddenException, Injectable } from '@nestjs/common';
import { FEATURE_REGISTRY, searchFeatures } from '@nh/shared';
import { AuthService } from '../auth/auth.service';
import { ControlPlaneService } from '../control-plane/control-plane.service';
import { ClinicalIntelService } from '../clinical-intel/clinical-intel.service';
import { AgentBridgeService } from './agent-bridge.service';

export type PrivilegeLevel = 'none' | 'low' | 'high';

export interface ProposedChange {
  path: string;
  before: string;
  after: string;
  impact: string;
}

export interface ProposedAction {
  id: string;
  title: string;
  privilege: PrivilegeLevel;
  kind: string;
  summary: string;
  changes: ProposedChange[];
  payload: Record<string, unknown>;
}

@Injectable()
export class AgentConsoleService {
  constructor(
    private auth: AuthService,
    private control: ControlPlaneService,
    private clinical: ClinicalIntelService,
    private agent: AgentBridgeService,
  ) {}

  async chat(tenantId: string, user: any, message: string, contextPath?: string) {
    const text = (message || '').trim();
    const lower = text.toLowerCase();
    const hits = searchFeatures(text).slice(0, 5);

    // navigation intents
    if (/打开|前往|跳转|去/.test(text) && hits[0]) {
      return this.reply(
        `可以打开「${hits[0].title}」。这是导航操作，无需提升权限。`,
        [],
        [{ type: 'navigate', path: hits[0].path, label: hits[0].title }],
      );
    }

    if (/搜索|找一下|功能/.test(text) || hits.length) {
      const list = (hits.length ? hits : FEATURE_REGISTRY.slice(0, 6))
        .map((f, i) => `${i + 1}. ${f.title} — ${f.description}`)
        .join('\n');
      return this.reply(`相关功能：\n${list}\n\n当前页：${contextPath || '/'}`, [], hits.slice(0, 3).map((f) => ({
        type: 'navigate',
        path: f.path,
        label: f.title,
      })));
    }

    if (/变量|灵敏度|咳嗽|敏捷|clinical\.|control/.test(lower) || /改.*配置|设置.*阈值/.test(text)) {
      const cfg = await this.clinical.getConfig(tenantId);
      const snap = await this.control.snapshot(tenantId);
      const action: ProposedAction = {
        id: `act_${Date.now()}`,
        title: '调整临床声学识别敏捷度',
        privilege: 'high',
        kind: 'clinical.config.update',
        summary: '将修改租户级声学识别参数，影响咳嗽/碰撞判定与自动推送行为。',
        changes: [
          {
            path: 'clinical.coughSensitivity',
            before: String(cfg?.coughSensitivity ?? 0.55),
            after: '0.62',
            impact: '咳嗽检出更敏感，误报可能上升',
          },
          {
            path: 'clinical.hardImpactThreshold',
            before: String(cfg?.hardImpactThreshold ?? 0.72),
            after: '0.68',
            impact: '硬碰撞更容易触发院内提醒',
          },
          {
            path: 'control.variable[clinical.cough_sensitivity]',
            before: snap.variables?.find((v: any) => v.key === 'clinical.cough_sensitivity')?.value ?? '0.55',
            after: '0.62',
            impact: '主控台运行变量同步',
          },
        ],
        payload: {
          coughSensitivity: 0.62,
          hardImpactThreshold: 0.68,
          syncControlVar: true,
        },
      };
      return this.reply(
        '我准备了一份**高权限**配置变更草案。请在右侧甄别框核对每条 before → after，输入管理员密码后再确认执行。',
        [action],
      );
    }

    if (/停用|禁用.*服务|关闭.*agent|服务/.test(text)) {
      const services = await this.control.listServices(tenantId);
      const agentSvc = services.find((s: any) => s.code === 'agent');
      const action: ProposedAction = {
        id: `act_${Date.now()}`,
        title: '停用 Agent Runtime 服务注册',
        privilege: 'high',
        kind: 'control.service.disable',
        summary: '停用服务注册表中的 agent 条目（不直接杀进程，但主控台将标记为禁用）。',
        changes: [
          {
            path: `serviceRegistry[${agentSvc?.code || 'agent'}].enabled`,
            before: String(agentSvc?.enabled ?? true),
            after: 'false',
            impact: '管理端探测与编排将跳过该服务',
          },
        ],
        payload: { code: 'agent', enabled: false, name: agentSvc?.name, baseUrl: agentSvc?.baseUrl },
      };
      return this.reply('这是高权限服务变更。确认前请核对返回框中的差异。', [action]);
    }

    if (/预诊|咳嗽事件|模拟/.test(text)) {
      return this.reply(
        '可用命令：\n• 「调整咳嗽灵敏度」→ 生成高权限配置草案\n• 「停用 agent 服务」→ 服务注册变更\n• 「打开临床智能」→ 导航\n\n高权限操作每次都需要管理员密码 + 变更甄别。',
        [],
        [{ type: 'navigate', path: '/clinical-intel', label: '声学异常与 AI 预诊' }],
      );
    }

    // try agent typeless if up
    try {
      const remote = await this.agent.post('/v1/typeless', {
        text,
        bed_id: 'admin-console',
        mode: 'console',
      });
      if (remote?.status && remote.status < 500 && remote.data) {
        const content =
          typeof remote.data === 'string'
            ? remote.data
            : remote.data.reply || remote.data.message || JSON.stringify(remote.data).slice(0, 800);
        return this.reply(String(content), []);
      }
    } catch {
      /* local fallback */
    }

    return this.reply(
      [
        '我是主控台 Agent（Codex 风格侧栏）。可以帮你：',
        '1. 搜索并打开功能模块',
        '2. 起草高权限变更（变量 / 服务 / 临床灵敏度）',
        '3. 执行前强制：变更甄别框 + 管理员密码',
        '',
        `你刚说：${text}`,
        contextPath ? `上下文路由：${contextPath}` : '',
      ]
        .filter(Boolean)
        .join('\n'),
      [],
    );
  }

  async execute(
    tenantId: string,
    user: any,
    body: {
      action: ProposedAction;
      password: string;
      elevateToken?: string;
    },
  ) {
    const action = body.action;
    if (!action) throw new ForbiddenException('缺少操作草案');

    if (action.privilege === 'high') {
      // 每次高权限：必须密码；若已有 elevateToken 再校验
      await this.auth.reauth(user.userId, body.password);
      if (body.elevateToken) {
        await this.auth.verifyElevate(body.elevateToken, user.userId);
      }
    }

    if (action.kind === 'clinical.config.update') {
      const updated = await this.clinical.upsertConfig(tenantId, action.payload);
      if (action.payload.syncControlVar) {
        await this.control.upsertVariable(tenantId, {
          key: 'clinical.cough_sensitivity',
          value: String(action.payload.coughSensitivity),
          groupName: 'clinical',
          description: '咳嗽识别灵敏度（Agent 确认写入）',
        });
        await this.control.upsertVariable(tenantId, {
          key: 'clinical.hard_impact_threshold',
          value: String(action.payload.hardImpactThreshold),
          groupName: 'clinical',
          description: '硬碰撞阈值（Agent 确认写入）',
        });
      }
      return { ok: true, result: updated, applied: action.changes };
    }

    if (action.kind === 'control.service.disable' || action.kind === 'control.service.update') {
      const services = await this.control.listServices(tenantId);
      const existing: any = services.find((s: any) => s.code === action.payload.code) || {};
      const updated = await this.control.upsertService(tenantId, {
        ...existing,
        code: action.payload.code,
        name: action.payload.name || existing.name || action.payload.code,
        baseUrl: action.payload.baseUrl || existing.baseUrl,
        enabled: action.payload.enabled,
      });
      return { ok: true, result: updated, applied: action.changes };
    }

    throw new ForbiddenException(`未实现的操作类型: ${action.kind}`);
  }

  private reply(content: string, actions: ProposedAction[], quickLinks: any[] = []) {
    return {
      role: 'assistant',
      content,
      actions,
      quickLinks,
      meta: {
        privilegeRequired: actions.some((a) => a.privilege === 'high'),
        style: 'codex-rail',
      },
    };
  }
}
