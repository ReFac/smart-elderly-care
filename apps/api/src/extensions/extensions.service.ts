import { Injectable } from '@nestjs/common';
import { FEATURE_REGISTRY, searchFeatures, type FeatureEntry } from '@nh/shared';

export interface DynamicExtension {
  id: string;
  title: string;
  group: string;
  path: string;
  apiPrefix: string;
  description: string;
  keywords: string[];
  enabled: boolean;
  createdAt: string;
}

export interface LearningEvent {
  id: string;
  kind: 'false_positive' | 'false_negative' | 'true_positive' | 'correction';
  source: string;
  payload: any;
  noiseInjected: number;
  createdAt: string;
}

@Injectable()
export class ExtensionsService {
  private dynamic: DynamicExtension[] = [];
  private learning: LearningEvent[] = [];
  private noiseBank: any[] = [];

  /** 静态注册表 + 动态扩展 */
  catalog() {
    return {
      builtin: FEATURE_REGISTRY,
      dynamic: this.dynamic,
      extensionPoints: [
        { id: 'module.route', desc: '注册管理端路由与侧栏' },
        { id: 'api.prefix', desc: '注册 Nest 业务 API 前缀' },
        { id: 'agent.skill', desc: '注册 Agent Skill / MCP Tool' },
        { id: 'family.widget', desc: '家属端可见组件' },
        { id: 'settings.key', desc: '系统设置项' },
      ],
    };
  }

  search(q: string) {
    const builtin = searchFeatures(q);
    const dyn = this.dynamic
      .map((d) => {
        const asFeature: FeatureEntry = {
          id: d.id,
          title: d.title,
          group: d.group as any,
          path: d.path,
          keywords: d.keywords,
          description: d.description,
          apiPrefix: d.apiPrefix,
          extensible: true,
        };
        return searchFeatures(q, [asFeature])[0];
      })
      .filter(Boolean);
    return [...builtin, ...dyn].sort((a, b) => (b?.score || 0) - (a?.score || 0));
  }

  register(body: Partial<DynamicExtension>) {
    const id = body.id || `ext_${Date.now()}`;
    const item: DynamicExtension = {
      id,
      title: body.title || id,
      group: body.group || 'system',
      path: body.path || `/ext/${id}`,
      apiPrefix: body.apiPrefix || `/api/ext/${id}`,
      description: body.description || '动态扩展模块（预留）',
      keywords: body.keywords || [],
      enabled: body.enabled !== false,
      createdAt: new Date().toISOString(),
    };
    this.dynamic = this.dynamic.filter((d) => d.id !== id).concat(item);
    return item;
  }

  listDynamic() {
    return this.dynamic;
  }

  /**
   * 学习闭环：人工修正后注入噪声样本。
   * - false_positive：提高阈值倾向 + 向负样本加噪声
   * - false_negative / correction：向正样本周边加噪声，避免过拟合漏报
   */
  learnFromCorrection(body: {
    kind: LearningEvent['kind'];
    source?: string;
    payload?: any;
    noiseScale?: number;
  }) {
    const scale = body.noiseScale ?? (body.kind === 'false_positive' ? 0.08 : 0.05);
    const base = body.payload || {};
    const injected: any[] = [];
    for (let i = 0; i < 3; i++) {
      const noisy = {
        ...base,
        confidence: clamp(
          Number(base.confidence ?? 0.5) + (Math.random() - 0.5) * 2 * scale,
          0,
          1,
        ),
        noise_tag: body.kind,
        jitter: (Math.random() - 0.5) * scale,
      };
      injected.push(noisy);
      this.noiseBank.push(noisy);
    }
    if (this.noiseBank.length > 2000) this.noiseBank = this.noiseBank.slice(-1500);

    const event: LearningEvent = {
      id: `lrn_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      kind: body.kind,
      source: body.source || 'admin',
      payload: base,
      noiseInjected: injected.length,
      createdAt: new Date().toISOString(),
    };
    this.learning.unshift(event);
    this.learning = this.learning.slice(0, 200);

    return {
      event,
      noiseSamples: injected,
      noiseBankSize: this.noiseBank.length,
      hint:
        body.kind === 'false_positive'
          ? '误报已学习：注入负样本噪声并建议上调融合阈值'
          : '漏报/修正已学习：注入正样本邻域噪声，提升召回鲁棒性',
    };
  }

  learningStats() {
    const byKind: Record<string, number> = {};
    for (const e of this.learning) byKind[e.kind] = (byKind[e.kind] || 0) + 1;
    return {
      totalEvents: this.learning.length,
      byKind,
      noiseBankSize: this.noiseBank.length,
      recent: this.learning.slice(0, 20),
    };
  }

  noiseBankSample(limit = 20) {
    return this.noiseBank.slice(-limit);
  }
}

function clamp(n: number, min: number, max: number) {
  return Math.max(min, Math.min(max, n));
}
