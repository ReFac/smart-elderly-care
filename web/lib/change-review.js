import { button, el, icon } from './ui.js';
import { detail } from './dialogs.js';

const titles = {
  'care.inquire': '登记接待',
  'care.admit': '办理入住',
  'care.transfer': '变更床位',
  'care.renew': '办理续住',
  'care.discharge': '办理离院',
  'care.leave': '登记请假',
  'care.assess': '保存能力评估',
  'care.approvePlan': '审核照护计划',
  'care.addTask': '新建照护工单',
  'care.completeTask': '完成照护工单',
  'care.quality': '登记服务抽检',
  'care.handover': '提交交班',
  'care.acceptHandover': '签收交班',
  'care.withdrawHandover': '撤回交班',
  'care.addMedication': '登记医嘱',
  'care.giveMedication': '登记给药',
  'care.reviewMedication': '复核医嘱',
  'care.vital': '记录健康体征',
  'care.resolveVital': '处理异常体征',
  'care.archive': '登记医疗档案',
  'care.screen': '登记筛查',
  'care.scheduleFollowup': '安排随访',
  'care.finishFollowup': '完成随访',
  'care.refer': '登记转介',
  'care.receiveReferral': '登记接收结果',
  'care.referralConsent': '更新转介授权',
  'care.exportReferral': '生成转介资料',
  'care.publishDrugRule': '发布用药规则',
  'care.retireDrugRule': '停用用药规则',
  'care.timelineSettings': '保存时间线设置',
  'dossier.profile': '更新长者档案',
  'family.consent': '登记长者的简报分享意愿',
  'family.subscribe': '设置家属站内简报订阅',
  'family.read': '签收家属站内简报',
  'dossier.relative': '更新亲属档案',
  'dossier.document': '存档医疗文书',
  'dossier.ocr': '将原件发送至 DeepSeek OCR',
  'dossier.reviewDocument': '复核医疗文书',
  'dossier.signSummary': '签署病情概括',
  'facility.addBeds': '增设床位',
  'facility.addBuilding': '新增楼栋',
  'facility.addCampus': '新增分院',
  'facility.addFloor': '新增楼层',
  'facility.addRoom': '新增房间',
  'facility.renameBuilding': '更名楼栋',
  'facility.setLayout': '保存平面图',
  'facility.setScene': '发布环境视点',
  'facility.updateCampus': '编辑分院',
  'facility.withdrawScene': '撤下环境视点',
  'access.create': '创建账号',
  'access.update': '更新账号与授权',
  'access.password': '修改账号口令',
  'access.settings': '保存机构界面',
  'access.mediaSettings': '变更识别工具开关',
  'account.changePassword': '修改登录密码',
  'portal.feedback': '提交服务反馈',
  'gw.confirm': '确认并完成工单',
  'gw.dismiss': '退回语音申请',
  'gw.ingest': '登记设备信号',
  'gw.propose': '提交待确认的工单改动',
  'gw.review': '保存预警复核',
  'media.agentVoice': 'Agent 语音转写',
  'agent.start': '启动 Agent 任务',
  'agent.publish': '发布 Agent 建议',
  'agent.cancel': '取消 Agent 任务',
  'ops.stock': '登记库存流水',
  'ops.addItem': '新增物资',
  'ops.shift': '登记排班',
  'ops.bill': '生成账单',
  'ops.deposit': '登记预存款',
  'ops.pay': '登记收款',
  'ops.importReceipt': '导入回执',
  'ops.paymentOrder': '创建支付订单',
  'ops.remindBill': '登记催缴',
  'ops.expense': '登记支出',
  'ops.submitReport': '冻结报送版本',
  'ops.reportReceipt': '保存报送回执',
  'ops.report': '生成报表',
  'ops.suggest': '生成专项建议',
  'ops.review': '审核专项建议',
  'history.undo': '撤销改动',
  'backup.create': '创建快照',
  'backup.verify': '验证恢复',
  'backup.link': '连接异地备份',
  'backup.retry': '重试备份',
};

const labels = {
  residentId: '长者',
  roomId: '房间',
  bedId: '床位',
  targetBedId: '目标床位',
  assignee: '执行人',
  taskId: '工单',
  accountId: '账号',
  id: '记录编号',
  role: '角色',
  permissions: '权限',
  campusId: '分院',
  campusIds: '分院范围',
  floorId: '楼层',
  buildingId: '楼栋',
  proposalId: '申请编号',
  runId: 'Agent 任务',
  requester: '申请人',
  scope: '范围',
  title: '名称',
  name: '姓名或名称',
  date: '日期',
  time: '时间',
  note: '记录',
  reason: '原因',
  method: '处理方式',
  contact: '联系方式',
  campusName: '分院',
  ward: '照护区',
  actorId: '经办账号',
  label: '名称',
  household: '家庭情况',
  basic: '基础资料',
  age: '年龄',
  gender: '性别',
  hometown: '籍贯',
  address: '住址',
  birthDate: '出生日期',
  executedAt: '实际执行时间',
  executionRoomLabel: '执行房间',
  operatorName: '经办人',
  completedAt: '完成时间',
  completedDate: '完成日期',
  completedBy: '执行人',
  completedById: '执行账号',
  executionRoomId: '执行房间',
  executionBedId: '执行床位',
  executionRoom: '执行房间',
  executionActorId: '执行账号',
  executionActorName: '执行人',
  operatorId: '操作人编号',
  revision: '版本',
  at: '记录时间',
  createdAt: '创建时间',
  updatedAt: '更新时间',
  scopeId: '范围编号',
  scopeType: '范围类型',
  key: '项目',
  value: '值',
  before: '改动前',
  after: '改动后',
  resident_id: '长者编号',
  localName: '楼栋名称',
  display_name: '姓名',
  order: '顺序',
  institution: '机构',
  bedCount: '床位数',
  number: '编号',
  filename: '原件名称',
  category: '类别',
  description: '描述',
  source: '来源',
  eventDate: '文书日期',
  pending: '待核实事项',
  consent: '发送授权',
  transcript: '转录原文',
  targetAction: '拟执行操作',
  enabled: '启用',
  kind: '类型',
  status: '状态',
  room: '房间',
  operator: '操作人',
  username: '登录名',
  displayName: '显示姓名',
  theme: '界面配色',
  brandName: '平台名称',
  institutionName: '机构名称',
  hiddenRoutes: '隐藏模块',
  amount: '金额',
  quantity: '数量',
  assigneeId: '接班人',
  itemId: '物资',
  billId: '账单',
  version: '版本',
  documentId: '文书',
  ocr: 'OCR 识别',
  asr: '语音转写',
  mergeEnabled: '合并展示',
  windowMinutes: '合并时间窗（分钟）',
  medicationId: '医嘱',
  planId: '计划',
  careSchedule: '照护记录',
};

export const actionTitle = (action) => titles[action] || action;
export const fieldLabel = (field) => labels[field] || field;

function printable(value) {
  if (Array.isArray(value)) return value.map(printable).join('、') || '无';
  if (value && typeof value === 'object')
    return Object.entries(value)
      .map(([k, v]) => fieldLabel(k) + ' ' + printable(v))
      .join('，');
  if (typeof value === 'boolean') return value ? '是' : '否';
  return value == null || value === '' ? '（空）' : String(value);
}

export function changePreview(state, action, payload, options = {}) {
  const dialog = [...document.querySelectorAll('dialog[open]')].at(-1);
  const controls = [...(dialog?.querySelectorAll('[name]') || [])];
  const targetTask = state.tasks?.find((r) => r.id === payload.taskId);
  const person = state.residents?.find(
    (r) => r.id === (payload.residentId || targetTask?.residentId),
  );
  const bed = state.beds?.find((r) => r.id === person?.bedId);
  const target =
    options.target ||
    [person?.name, bed?.label, targetTask?.title].filter(Boolean).join(' · ') ||
    payload.name ||
    dialog?.getAttribute('aria-label') ||
    state.uiSettings.institutionName;
  const fields = [];
  for (const [key, value] of Object.entries(payload)) {
    if (['imageBase64', 'requestId', 'imageHash', 'transcriptId', 'mime'].includes(key)) continue;
    const input = controls.find((i) => i.name === key);
    const label =
      input?.labels?.[0]?.querySelector('span')?.textContent?.replace(/\s*\*\s*$/, '') ||
      fieldLabel(key);
    let text;
    if (/password|secret|api.?key|access.?token/i.test(key) || input?.type === 'password')
      text = '••••••（已填写）';
    else if (input?.tagName === 'SELECT')
      text = [...input.selectedOptions].map((o) => o.textContent).join('、');
    else if (key === 'residentId' && person) text = person.name;
    else if (key === 'taskId' && targetTask) text = targetTask.title;
    else if (key === 'targetAction') text = actionTitle(value);
    else text = printable(value);
    fields.push([label, text]);
  }
  if (payload.imageBase64) fields.push(['原件', '随本次操作加密归档']);
  return {
    title: options.title || actionTitle(action),
    target,
    fields: options.fields || fields,
    ...options,
  };
}

export function commentInput() {
  const label = el('label', 'change-comment');
  const input = el('input', 'fx-input');
  input.maxLength = 240;
  input.placeholder = '说明本次变更原因（选填）';
  label.append(el('span', '', '变更说明'), input);
  return { element: label, read: () => input.value.trim() };
}

export function confirmChange({
  title,
  target,
  fields = [],
  confirmLabel = '确认执行',
  allowComment = false,
}) {
  return new Promise((resolve) => {
    const content = el('div', 'change-review');
    const place = el('div', 'change-target');
    place.append(icon('location', 17), el('span', '', target || '机构工作区'));
    content.append(place, el('h3', '', title));
    if (fields.length) {
      const list = el('dl', 'change-fields');
      for (const [name, value] of fields) {
        const entry = el('div');
        entry.append(el('dt', '', name), el('dd', '', printable(value)));
        list.append(entry);
      }
      content.append(list);
    }
    const comment = allowComment ? commentInput() : null;
    if (comment) content.append(comment.element);
    const footer = el('div', 'change-actions');
    const dialog = detail('确认改动', content);
    dialog.classList.add('change-review-dialog');
    let decision = null;
    const back = button('返回', () => dialog.close());
    footer.append(
      back,
      button(
        confirmLabel,
        () => {
          decision = { comment: comment?.read() || '' };
          dialog.close();
        },
        'primary',
        'check',
      ),
    );
    content.append(footer);
    back.focus();
    dialog.addEventListener('close', () => resolve(decision), { once: true });
  });
}
