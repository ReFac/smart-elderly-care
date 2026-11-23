/** 统一功能 / 设置注册表：主管理员视角可检索、可扩展 */

export type ModuleGroup =
  | 'ops'
  | 'clinical'
  | 'family'
  | 'caregiver'
  | 'agent'
  | 'system';

export interface FeatureEntry {
  id: string
  title: string
  group: ModuleGroup
  path: string
  keywords: string[]
  description: string
  apiPrefix: string
  extensible: boolean
  settingsKeys?: string[]
}

export const MODULE_GROUP_LABELS: Record<ModuleGroup, string> = {
  ops: '运营管理',
  clinical: '医护业务',
  family: '家属端视角',
  caregiver: '护理端视角',
  agent: 'Agent 智能体',
  system: '系统与扩展',
}

export const FEATURE_REGISTRY: FeatureEntry[] = [
  {
    id: 'dashboard',
    title: '运营看板',
    group: 'ops',
    path: '/dashboard',
    keywords: ['看板', '入住率', '欠费', 'overview', 'dashboard'],
    description: '入住率、空床、待办、营收概览',
    apiPrefix: '/api/dashboard',
    extensible: true,
  },
  {
    id: 'beds',
    title: '楼层床位',
    group: 'ops',
    path: '/beds',
    keywords: ['床位', '楼层', '房间', '调床', 'bed'],
    description: '建筑楼层床位视图与状态',
    apiPrefix: '/api/org',
    extensible: true,
  },
  {
    id: 'elders',
    title: '老人档案',
    group: 'ops',
    path: '/elders',
    keywords: ['档案', '入住', '合同', '健康档案', 'elder'],
    description: '老人建档、健康、合同、调床',
    apiPrefix: '/api/elders',
    extensible: true,
  },
  {
    id: 'care',
    title: '照护服务',
    group: 'ops',
    path: '/care',
    keywords: ['照护', '打卡', '工单', '探视', 'care'],
    description: '照护计划、打卡、临时服务、探视',
    apiPrefix: '/api/care',
    extensible: true,
  },
  {
    id: 'billing',
    title: '收费财务',
    group: 'ops',
    path: '/billing',
    keywords: ['账单', '收费', '缴费', '押金', 'finance'],
    description: '计费规则、账单、缴费、欠费',
    apiPrefix: '/api/billing',
    extensible: true,
  },
  {
    id: 'meals',
    title: '食堂餐食',
    group: 'ops',
    path: '/meals',
    keywords: ['食堂', '食谱', '餐食', '忌口', 'meal'],
    description: '周食谱与忌口管理',
    apiPrefix: '/api/meals',
    extensible: true,
  },
  {
    id: 'medical',
    title: '医护健康',
    group: 'clinical',
    path: '/medical',
    keywords: ['体征', '发药', '医嘱', '转诊', 'medical'],
    description: '体征、药品、发药、体检随访、医嘱转诊',
    apiPrefix: '/api/medical',
    extensible: true,
  },
  {
    id: 'ltc',
    title: '长护险',
    group: 'clinical',
    path: '/ltc',
    keywords: ['长护险', '评估', '对账', '申报', 'ltc'],
    description: '评估、服务留痕、对账导出',
    apiPrefix: '/api/ltc',
    extensible: true,
  },
  {
    id: 'inventory',
    title: '后勤物资',
    group: 'ops',
    path: '/inventory',
    keywords: ['库存', '物资', '报修', '纸尿裤', 'inventory'],
    description: '库存出入库、低库存、报修',
    apiPrefix: '/api/inventory',
    extensible: true,
  },
  {
    id: 'hr',
    title: '人事排班',
    group: 'ops',
    path: '/hr',
    keywords: ['员工', '排班', '考勤', '绩效', 'hr'],
    description: '员工档案、排班、考勤、绩效',
    apiPrefix: '/api/hr',
    extensible: true,
  },
  {
    id: 'security',
    title: '安防告警',
    group: 'ops',
    path: '/security',
    keywords: ['安防', '告警', 'SOS', '门禁', 'security'],
    description: '告警中心、风险扫描、门禁',
    apiPrefix: '/api/security',
    extensible: true,
  },
  {
    id: 'reports',
    title: '报表报送',
    group: 'ops',
    path: '/reports',
    keywords: ['报表', '民政', '报送', '导出', 'report'],
    description: '民政月报生成与导出',
    apiPrefix: '/api/reports',
    extensible: true,
  },
  {
    id: 'family_portal',
    title: '家属端总览',
    group: 'family',
    path: '/family-portal',
    keywords: ['家属', '账单透明', '今日餐食', 'family', '小程序'],
    description: '主管理员预览/管理家属端可见信息',
    apiPrefix: '/api/billing,/api/meals',
    extensible: true,
    settingsKeys: ['family.bill_transparency', 'family.meal_visibility'],
  },
  {
    id: 'caregiver_portal',
    title: '护理端总览',
    group: 'caregiver',
    path: '/caregiver-portal',
    keywords: ['护理员', '打卡', '工单', 'caregiver', 'app'],
    description: '主管理员预览护理端今日任务与异常',
    apiPrefix: '/api/care',
    extensible: true,
  },
  {
    id: 'agent',
    title: 'Agent 智能体',
    group: 'agent',
    path: '/agent',
    keywords: ['agent', '融合', '语音', 'harness', 'mcp', 'deepseek'],
    description: '感知融合、语音照护、会议纪要、审计复核',
    apiPrefix: '/api/agent',
    extensible: true,
    settingsKeys: ['agent.llm', 'agent.fusion', 'agent.noise_learning'],
  },
  {
    id: 'learning',
    title: '学习与噪声',
    group: 'agent',
    path: '/learning',
    keywords: ['学习', '误判', '噪声', '反馈', 'noise', 'learning'],
    description: '人工修正后自动加噪声，持续降低误报',
    apiPrefix: '/api/extensions/learning',
    extensible: true,
    settingsKeys: ['learning.noise_on_fp', 'learning.noise_on_fn', 'learning.auto_tune'],
  },
  {
    id: 'settings',
    title: '系统设置',
    group: 'system',
    path: '/settings',
    keywords: ['设置', '功能开关', 'AI', 'LLM', 'OCR', 'settings'],
    description: '功能开关、LLM/OCR API 配置',
    apiPrefix: '/api/settings',
    extensible: true,
    settingsKeys: ['ai.baseUrl', 'ai.model', 'feature_flags'],
  },
  {
    id: 'extensions',
    title: '扩展注册中心',
    group: 'system',
    path: '/extensions',
    keywords: ['扩展', '插件', '新接口', 'registry', 'extension'],
    description: '注册新业务接口与模块，预留扩展点',
    apiPrefix: '/api/extensions',
    extensible: true,
  },
  {
    id: 'control_plane',
    title: '变量/API/服务总控',
    group: 'system',
    path: '/control-plane',
    keywords: ['变量', '服务', 'API', '总控', 'control', 'config', '敏捷'],
    description: '主管理员修改全部运行变量、服务启停与 API 元数据',
    apiPrefix: '/api/control',
    extensible: true,
    settingsKeys: ['app.name', 'agent.base_url', 'mobile.wechat_oa_enabled', 'tour.default_fov'],
  },
  {
    id: 'room_tours',
    title: '3D 房态导览',
    group: 'ops',
    path: '/room-tours',
    keywords: ['3D', '全景', '导览', '房态', 'tour', 'panorama', '微信'],
    description: '全景/3D 房态导览与热点，用户端公开接口',
    apiPrefix: '/api/tours',
    extensible: true,
    settingsKeys: ['tour.default_fov'],
  },
  {
    id: 'clinical_intel',
    title: '声学异常与 AI 预诊',
    group: 'clinical',
    path: '/clinical-intel',
    keywords: ['咳嗽', '麦克风', '碰撞', '预诊', 'acoustic', 'SOTA', '推送家属'],
    description: '床头麦克风异常识别、档案更新、AI 预诊与院内/家属推送（接口预留）',
    apiPrefix: '/api/clinical',
    extensible: true,
    settingsKeys: [
      'clinical.cough_sensitivity',
      'clinical.hard_impact_threshold',
      'clinical.inference_base_url',
      'clinical.auto_facility_push',
    ],
  },
]

/** 简易模糊匹配：子串 + 字符序 + 关键词 */
export function fuzzyScore(query: string, text: string): number {
  const q = query.trim().toLowerCase()
  const t = text.toLowerCase()
  if (!q) return 1
  if (t.includes(q)) return 1 + q.length / Math.max(t.length, 1)
  let qi = 0
  for (let i = 0; i < t.length && qi < q.length; i++) {
    if (t[i] === q[qi]) qi++
  }
  if (qi === q.length) return 0.55 + qi / (t.length + 5)
  // bigram overlap
  const grams = (s: string) => {
    const out: string[] = []
    for (let i = 0; i < s.length - 1; i++) out.push(s.slice(i, i + 2))
    return out
  }
  const qg = new Set(grams(q))
  const tg = grams(t)
  if (!qg.size) return 0
  let hit = 0
  for (const g of tg) if (qg.has(g)) hit++
  return hit / qg.size
}

export function searchFeatures(query: string, registry: FeatureEntry[] = FEATURE_REGISTRY): Array<FeatureEntry & { score: number }> {
  const q = query.trim()
  if (!q) return registry.map((f) => ({ ...f, score: 1 }))
  return registry
    .map((f) => {
      const hay = [f.title, f.description, f.id, f.apiPrefix, ...(f.keywords || []), ...(f.settingsKeys || [])].join(' ')
      const score = Math.max(
        fuzzyScore(q, f.title),
        fuzzyScore(q, hay),
        ...f.keywords.map((k) => fuzzyScore(q, k) * 1.1),
      )
      return { ...f, score }
    })
    .filter((f) => f.score >= 0.35)
    .sort((a, b) => b.score - a.score)
}
