import { groups } from '../lib/navigation.js';
import { btn, node } from './shared.js';

const grantGroups = [
  ['入住与照护', ['residents', 'intake', 'care', 'care.schedule', 'care.areas', 'facility.manage', 'clinical', 'clinical.rules', 'health.overview']],
  ['医疗档案与亲属', ['medical', 'medical.write', 'relatives', 'family.share']],
  ['机构运营', ['inventory', 'finance', 'longCare', 'shifts', 'reports']],
  ['智能协作与设备', ['assistants', 'gateway.simulate', 'alerts', 'voice', 'voice.confirm']],
  ['人员与审计', ['staff.manage', 'audit']],
];

// Labels describe the action IDs returned by the server for this account.
const commands = {
  ltci: ['长期护理保险', { record: '登记长护险办理凭证' }],
  care: [
    '照护业务',
    {
      inquire: '接待登记',
      admit: '办理入住',
      transfer: '转床',
      renew: '续住',
      discharge: '退住',
      leave: '请假',
      assess: '登记评估',
      approvePlan: '复核照护计划',
      addTask: '派发工单',
      areaSave: '维护楼栋区域',
      areaArchive: '归档楼栋区域',
      areaMap: '调整照护范围',
      areaAssign: '分配护工的照护区域',
      saveSchedule: '配置定时工单',
      setScheduleEnabled: '暂停或启用定时工单',
      scheduleMenu: '更新指定日期菜品',
      confirmScheduledMeal: '签认伙食工单',
      completeTask: '登记工单执行',
      quality: '服务抽检',
      handover: '登记交班',
      acceptHandover: '签收本人交班',
      withdrawHandover: '撤回本人交班',
      confirmMedRound: '逐位签认床旁服药',
      addMedication: '登记医嘱',
      giveMedication: '登记给药',
      reviewMedication: '复核医嘱',
      vital: '录入体征',
      reportMedication: '登记长者本人自报的用药',
      resolveVital: '复核异常体征',
      archive: '登记健康记录',
      screen: '登记筛查',
      scheduleFollowup: '安排干预与随访',
      finishFollowup: '记录干预效果',
      refer: '创建转介',
      receiveReferral: '登记接收回执',
      referralConsent: '登记或撤回资料授权',
      exportReferral: '导出授权衔接资料',
      publishDrugRule: '发布核准用药规则',
      retireDrugRule: '停用核查规则',
    },
  ],
  dossier: [
    '档案维护',
    {
      profile: '维护长者资料',
      document: '存档医疗文书',
      relative: '维护亲属资料',
      ocr: '识别已存原件',
      reviewDocument: '签认文书回填',
      signSummary: '签认档案摘要',
    },
  ],
  ops: [
    '运营业务',
    {
      stock: '办理出入库',
      addItem: '建立物资品目',
      shift: '登记排班',
      bill: '生成账单',
      deposit: '登记预交',
      paymentFees: '维护收款手续费',
      pay: '核销账单',
      paymentOrder: '登记商户订单',
      importReceipt: '核销渠道凭证',
      remindBill: '登记催缴',
      expense: '登记支出',
      submitReport: '登记报送版本',
      reportReceipt: '登记报送回执',
      report: '生成报送草稿',
      suggest: '生成建议',
      review: '审核建议',
    },
  ],
  agent: ['业务简报', { start: '整理简报', publish: '发布简报', cancel: '取消协作' }],
  gw: [
    '设备与变更',
    {
      ingest: '登记模拟事件',
      review: '复核预警',
      propose: '发起变更',
      confirm: '确认变更',
      dismiss: '退回变更',
    },
  ],
  facility: [
    '空间管理',
    {
      addBuilding: '新增楼栋',
      addFloor: '新增楼层',
      addRoom: '新增房间',
      updateRoom: '修改房型与床位',
      addBeds: '新增床位',
      linkBed: '关联床位',
      setLayout: '登记平面图',
      setScene: '发布环境视点',
      withdrawScene: '撤回环境视点',
    },
  ],
  access: [
    '机构账号',
    {
      create: '创建账号',
      update: '调整账号与授权',
      settings: '设置机构界面',
    },
  ],
  account: ['个人账号', { changePassword: '修改本人密码' }],
  family: ['巡查简报', { consent: '登记长者分享意愿', subscribe: '本人订阅站内简报', read: '签收本人简报' }],
  portal: ['长者与家属服务', { feedback: '评价已完成的服务' }],
};

export function grantPicker(options, current) {
  const element = node('div', 'access-grant-groups');
  const boxes = new Map();
  const known = new Set(grantGroups.flatMap(([, ids]) => ids));
  const other = Object.keys(options).filter((key) => !known.has(key));
  for (const [title, keys] of [...grantGroups, ['其他授权', other]]) {
    const available = keys.filter((key) => Object.hasOwn(options, key));
    if (!available.length) continue;
    const group = node('fieldset', 'access-grant-group', node('legend', '', title));
    const items = node('div', 'access-group-choices');
    for (const key of available) {
      const check = node('input');
      check.type = 'checkbox';
      check.name = 'permission';
      check.value = key;
      check.checked = current.includes(key);
      boxes.set(key, check);
      items.append(node('label', 'access-check', [check, node('span', '', options[key])]));
    }
    group.append(items);
    element.append(group);
  }
  element.addEventListener('change', ({ target }) => {
    if (target.value === 'family.share' && target.checked && boxes.has('relatives'))
      boxes.get('relatives').checked = true;
    if (target.value === 'relatives' && !target.checked && boxes.has('family.share'))
      boxes.get('family.share').checked = false;
    if (target.value === 'medical.write' && target.checked && boxes.has('medical'))
      boxes.get('medical').checked = true;
    if (target.value === 'medical' && !target.checked && boxes.has('medical.write'))
      boxes.get('medical.write').checked = false;
  });
  return {
    element,
    read: () => [...boxes].filter(([, input]) => input.checked).map(([key]) => key),
    write: (values) =>
      boxes.forEach((input, key) => {
        input.checked = values.includes(key);
      }),
  };
}

function scopeRow(label, values) {
  return node('div', 'access-scope-row', [
    node('strong', '', label),
    node(
      'div',
      'access-scope-values',
      values.map((s) => node('span', '', s)),
    ),
  ]);
}

export function capabilitySummary(ctx, account) {
  const visible = account.routes.filter((key) => !ctx.state.uiSettings.hiddenRoutes.includes(key));
  const layout = node('div', 'access-capabilities');
  const routePanel = node(
    'section',
    'access-capability-section',
    node('h3', '', '工作台入口 · ' + visible.length),
  );
  for (const [group, items] of groups) {
    const labels = items.filter(([key]) => visible.includes(key)).map(([, label]) => label);
    if (labels.length) routePanel.append(scopeRow(group, labels));
  }
  const actionList = account.allowedActions || [];
  const actions = node('details', 'access-capability-section');
  actions.append(node('summary', '', '可办理操作 · ' + actionList.length));
  const byDomain = new Map();
  for (const action of actionList) {
    const [domain, name] = action.split('.');
    const [label, names] = commands[domain] || [domain, {}];
    if (!byDomain.has(label)) byDomain.set(label, []);
    byDomain.get(label).push(names[name] || action);
  }
  for (const [label, items] of byDomain) actions.append(scopeRow(label, items));
  if (!actionList.length) actions.append(node('p', 'fx-muted', '当前授权没有业务写入操作。'));
  layout.append(routePanel, actions);
  return layout;
}

export function draftPreview(ctx, form, payload) {
  const output = node('div', 'access-draft-output');
  output.setAttribute('aria-live', 'polite');
  let version = 0;
  const preview = btn(ctx, '预览工作台权限', async () => {
    const sent = ++version;
    preview.disabled = true;
    output.textContent = '正在核对授权…';
    try {
      const response = await fetch('/api/access/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload()),
      });
      const result = await response.json();
      if (version !== sent || !form.isConnected) return;
      if (!response.ok) throw new Error(result.error || '暂时无法预览授权。');
      output.replaceChildren(capabilitySummary(ctx, result));
    } catch (error) {
      if (version === sent && form.isConnected)
        output.textContent = error.message || '读取失败，请重新预览。';
    } finally {
      if (version === sent) preview.disabled = false;
    }
  });
  form.addEventListener('change', (event) => {
    if (!['role', 'permission', 'campusId'].includes(event.target.name)) return;
    version++;
    preview.disabled = false;
    output.replaceChildren();
  });
  return node('div', 'access-draft-preview', [preview, output]);
}
