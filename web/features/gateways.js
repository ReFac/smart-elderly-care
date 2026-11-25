import { staffLabel } from './people-labels.js';
import { staffNotices } from './assistant-actions.js';
import { commentInput } from '../lib/change-review.js';
import { voiceProposal } from './speech-input.js';
import { roundsInbox } from './rounds-desk.js';
import { canOpenPermissionRequests, permissionRequestsPanel } from './permission-requests.js';
import {
  node,
  page,
  btn,
  choose,
  facts,
  table,
  named,
  link,
  section,
  badge,
  runForm,
  field,
  memo,
  select,
  options,
  residentName,
  tabs,
  today,
} from './shared.js';

const sources = {
  youle: '优乐模型',
  radar: '超声波 / 雷达',
  sensor: '房间传感器',
  mijia: '米家授权设备',
  badge: '护理工牌',
};
const signals = { possible_fall: '疑似跌倒', prolonged_bedrest: '持续卧床提示' };

function has(ctx, permission) {
  const user = ctx.state.user;
  return user?.kind === 'owner' || user?.permissions?.includes(permission);
}
const choices = (obj) => Object.entries(obj).map(([value, label]) => ({ value, label }));
const roomName = (bed) => bed.ward + ' / ' + bed.label.replace(/-[^-]+$/, '');
const uniqueId = () =>
  Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
    byte.toString(16).padStart(2, '0'),
  ).join('');

function simulate(ctx) {
  const rooms = new Map();
  for (const bed of ctx.state.beds) if (!rooms.has(roomName(bed))) rooms.set(roomName(bed), bed.id);
  runForm(ctx, {
    title: '登记模拟信号',
    action: 'gw.ingest',
    description:
      '模拟设备上报一次观测。系统记录当时房间内的在住长辈，护士现场复核后再记入相应档案。',
    fields: [
      select('source', '设备来源', choices(sources)),
      select('signal', '检测信号', choices(signals)),
      select(
        'bedId',
        '观测房间',
        Array.from(rooms, ([label, value]) => ({ value, label })),
      ),
      field('eventId', '源事件编号', { value: uniqueId() }),
      field('evidenceRef', '图片、示意图或片段的证据编号', { required: false }),
      memo('observation', '设备观测摘要'),
    ],
    submitLabel: '登记待复核预警',
  });
}

function newProposal(ctx) {
  const tasks = ctx.state.tasks.filter((t) => t.status === '待执行' && t.date <= today(ctx));
  return voiceProposal(
    ctx,
    tasks.map((t) => [
      t.id,
      residentName(ctx, t.residentId) + ' · ' + t.title + ' · ' + t.date + ' ' + t.time,
    ]),
    uniqueId(),
  );
}

function review(ctx, row) {
  const names = row.candidates.map((id) => ({ value: id, label: residentName(ctx, id) }));
  runForm(ctx, {
    title: '护士现场复核',
    action: 'gw.review',
    description:
      row.room +
      ' · ' +
      signals[row.signal] +
      '。请核对现场信息。已核实事件将追加到所选长辈的历史档案。',
    fields: [
      select(
        'decision',
        '复核结论',
        options(row.candidates.length ? ['已核实', '误报', '无法核实'] : ['误报', '无法核实']),
      ),
      select(
        'residentId',
        '现场核实的长辈',
        [{ value: '', label: '请选择，误报或无法核实可留空' }, ...names],
        { required: false },
      ),
      memo('note', '现场情况与处置记录', true),
    ],
    map: (v) => ({ ...v, alertId: row.id }),
    submitLabel: '保存复核结论',
  });
}

const stamp = (value) => (value ? value.slice(0, 19).replace('T', ' ') : '—');

function mark(ctx, name, tone = '') {
  return node('span', 'gw-mark ' + tone, ctx.ui.icon(name, 20));
}

export function inspectAlert(ctx, row) {
  const pending = row.status === '待复核';
  const headline = node('div', 'gw-event-heading', [
    mark(ctx, 'bell', pending ? 'gw-gold' : ''),
    node('div', '', [node('strong', '', row.room), node('small', '', sources[row.source])]),
    badge(ctx, row.status, pending ? 'amber' : 'blue'),
  ]);
  const observed = row.observations.map((entry) =>
    node('li', '', [
      node('div', 'gw-step-head', [
        node('h3', '', sources[entry.source] + '观测'),
        node('time', '', stamp(entry.observedAt)),
      ]),
      node('p', '', entry.observation || '设备未附观测摘要'),
      facts([
        ['设备提示的长辈', row.residentHint ? residentName(ctx, row.residentHint) : '待现场核实'],
        ['证据编号', entry.evidenceRef],
        ['源事件编号', entry.eventId],
      ]),
    ]),
  );
  const resolution = node('li', pending ? 'gw-step-pending' : '', [
    node('div', 'gw-step-head', [
      node('h3', '', '现场复核'),
      node('time', '', pending ? '待处理' : stamp(row.reviewedAt)),
    ]),
    pending
      ? node('p', '', '护士核实房间和长辈后，可填写现场情况。')
      : node('p', '', row.reviewNote),
    pending
      ? btn(ctx, '填写复核结论', () => review(ctx, row), 'primary')
      : facts([
          ['确认长辈', residentName(ctx, row.residentId)],
          ['复核人账号', row.reviewedBy],
        ]),
  ]);
  ctx.detail(
    signals[row.signal],
    node('div', 'gw-detail', [headline, node('ol', 'gw-steps', [observed, resolution])]),
  );
}

function changePreview(ctx, task, row) {
  const record = (title, current, note, actor) =>
    node('section', 'gw-change-column', [
      node('h3', '', title),
      facts([
        ['工单状态', current],
        ['执行记录', note],
        ['执行人', actor],
      ]),
    ]);
  return node('div', 'gw-change', [
    record(
      '当前工单',
      task?.status || '不可用',
      task?.note || '尚未填写',
      task?.operator ? staffLabel(ctx, task.operator, task.operatorId) : '待登记',
    ),
    record('确认后写入', '已完成', row.note, staffLabel(ctx, ctx.state.user)),
  ]);
}

export async function confirmProposal(ctx, row, trigger) {
  try {
    const changes = await ctx.get('/api/voice-proposals/' + encodeURIComponent(row.id));
    if (!trigger.isConnected) return;
    row = { ...row, ...changes };
  } catch (error) {
    ctx.toast(error.message);
    return;
  }
  const task = ctx.state.tasks.find((t) => t.id === row.taskId);
  const comment = commentInput();
  const approve = btn(
    ctx,
    '确认并完成工单',
    async () => {
      approve.disabled = true;
      try {
        await ctx.command(
          'gw.confirm',
          { proposalId: row.id },
          { confirmed: true, comment: comment.read() },
        );
      } finally {
        approve.disabled = false;
      }
    },
    'primary',
  );
  const dismiss = btn(ctx, '退回申请', () => {
    runForm(ctx, {
      title: '退回语音申请',
      action: 'gw.dismiss',
      fields: [memo('reason', '退回原因', true)],
      map: (v) => ({ ...v, proposalId: row.id }),
      submitLabel: '确认退回',
    });
    const dialog = document.querySelector('dialog[open]:last-of-type');
    if (dialog) dialog.dataset.proposalId = row.id;
  });
  const content = node('div', 'gw-detail', [
    node('div', 'gw-event-heading', [
      mark(ctx, 'care'),
      node('div', '', [node('strong', '', row.title), node('small', '', row.taskId)]),
      badge(ctx, '待确认', 'amber'),
    ]),
    facts([
      ['服务长辈', residentName(ctx, row.residentId)],
      ['申请时房间', row.room],
      ['申请人', row.requester],
      ['申请时间', stamp(row.createdAt)],
    ]),
    node('section', 'gw-transcript', [
      node('h3', '', '转写原文'),
      node('blockquote', '', row.transcript),
    ]),
    changePreview(ctx, task, row),
    comment.element,
    node('footer', 'gw-confirm-foot', [
      node('small', '', '确认后写入工单并从共用队列移除。'),
      choose(dismiss, approve),
    ]),
  ]);
  ctx.detail('确认语音申请', content).dataset.proposalId = row.id;
}

function queuePanel(ctx, alerts) {
  if (alerts) {
    const sourceNames = r => r.observations.map(event=>sources[event.source] || event.source).join('、');
    return table(ctx,{
      title:'房间设备事件',rows:ctx.state.gatewayAlerts,empty:'当前没有设备预警记录',
      search:{placeholder:'搜索房间、事件编号或设备来源',
        value:r=>[r.room,r.priority,signals[r.signal],sourceNames(r),...r.observations.map(o=>o.eventId)].join(' ')},
      filter:{label:'复核状态',options:['待复核','已复核'],initial:'待复核',all:'全部预警',
        matches:(r,status)=>(r.status==='待复核')===(status==='待复核')},
      cols:[{label:'房间',view:r=>r.room},{label:'预警事项',view:r=>named(signals[r.signal] || r.signal,r.observation)},
        {label:'设备来源',view:sourceNames},{label:'优先级',view:r=>badge(ctx,r.priority)},
        {label:'复核状态',view:r=>badge(ctx,r.status)},
        {label:'操作',align:'end',view:r=>link(ctx,r.status==='待复核'?'查看并复核':'查看记录',()=>inspectAlert(ctx,r))}],
    });
  }
  return table(ctx,{title:'待确认语音申请',rows:ctx.state.voiceQueue,empty:'当前没有待确认申请',
    search:{placeholder:'搜索房间、工单或申请人',value:r=>[r.room,r.title,r.requester,residentName(ctx,r.residentId)].join(' ')},
    cols:[{label:'工单',view:r=>r.title},{label:'房间',view:r=>r.room},{label:'长辈',view:r=>residentName(ctx,r.residentId)},
      {label:'申请人',view:r=>r.requester},{label:'操作',align:'end',view:r=>
        link(ctx,'核对改动',evt=>confirmProposal(ctx,r,evt.currentTarget))}],
  });
}

function inbox(ctx) {
  const actions = choose(), views = [];
  if (has(ctx, 'gateway.simulate')) actions.append(btn(ctx, '模拟设备信号', () => simulate(ctx)));
  if (has(ctx, 'voice') && has(ctx, 'care'))
    actions.append(btn(ctx, '登记语音草稿', () => newProposal(ctx), 'primary'));
  if (has(ctx, 'audit') && ctx.available('activity'))
    actions.append(btn(ctx, '查看操作日志', () => ctx.go('activity')));
  if (has(ctx, 'alerts')) {
    views.push(['alerts', '设备预警', () => queuePanel(ctx, true)]);
  }
  if (has(ctx, 'voice.confirm') && has(ctx, 'care')) {
    views.push(['voice', '待确认语音', () => queuePanel(ctx, false)]);
  }
  if (has(ctx, 'care') || has(ctx, 'clinical')) {
    views.push(['rounds', '巡查提醒', () => roundsInbox(ctx)]);
  }
  if (canOpenPermissionRequests(ctx)) {
    views.push(['permissionRequests', '权限申请', () => permissionRequestsPanel(ctx)]);
  }
  if (ctx.state.user.kind !== 'family') {
    views.push(['notices', '全员通知', () => staffNotices(ctx)]);
  }
  let queue;
  if (views.length) {
    queue = tabs('inbox', views);
  } else queue = ctx.ui.empty('可以通过上方按钮登记设备观测或提交语音变更申请。');
  return page(ctx, '预警与人工确认', '', actions, queue);
}



function schemaDetails(ctx, title, schema, open = false) {
  const fields = Object.entries(schema.properties || {});
  const rows = fields.map(([name, spec]) => {
    const notes = [];
    if (spec.format) notes.push(spec.format);
    if (spec.enum) notes.push(spec.enum.join(' / '));
    if (spec.items) notes.push('成员 ' + spec.items.type);
    if (spec.minimum != null) notes.push('≥ ' + spec.minimum);
    if (spec.maximum != null) notes.push('≤ ' + spec.maximum);
    if (spec.minLength != null) notes.push('最少 ' + spec.minLength + ' 字符');
    if (spec.maxLength != null) notes.push('最多 ' + spec.maxLength + ' 字符');
    if (spec.pattern) notes.push(spec.pattern);
    return node('tr', '', [
      node('th', '', node('code', '', name)),
      node('td', '', spec.type),
      node('td', '', schema.required?.includes(name) ? '必填' : '选填'),
      node('td', '', notes.join(' · ') || '—'),
    ]);
  });
  const raw = node('details', 'gw-raw', [
    node('summary', '', '完整 JSON Schema'),
    node('pre', '', JSON.stringify(schema, null, 2)),
  ]);
  const table = node('table', 'gw-field-table', [
    node(
      'thead',
      '',
      node(
        'tr',
        '',
        ['字段', '类型', '填写规则', '约束'].map((h) => node('th', '', h)),
      ),
    ),
    node('tbody', '', rows),
  ]);
  table.setAttribute('aria-label', title);
  const box = node('details', 'gw-schema', [
    node('summary', '', [
      node('strong', '', title),
      node('span', '', fields.length + ' 个字段'),
      ctx.ui.icon('down', 15),
    ]),
    node('div', 'gw-schema-body', [node('div', 'gw-fields-scroll', table), raw]),
  ]);
  box.open = open;
  return box;
}

function inspectContract(ctx, row) {
  ctx.detail(
    row.title,
    node('div', 'gw-detail', [
      node('div', 'gw-contract-path', [node('b', '', row.method), node('code', '', row.path)]),
      facts([
        ['接口版本', row.version],
        [
          '资料依据',
          row.pages.length ? '工牌产品介绍第 ' + row.pages.join('、') + ' 页' : '机构补充需求',
        ],
        ['当前响应', 'HTTP 501 · 待接入'],
        ['配置权限', row.ownerOnly ? '仅 Owner' : '按机构授权'],
      ]),
      section('能力说明', node('p', 'gw-description', row.description)),
      section('接入条件', node('p', 'gw-description', row.policy)),
      schemaDetails(ctx, '请求参数', row.requestSchema, true),
      schemaDetails(ctx, '适配器响应', row.responseSchema),
    ]),
  );
}

function integrations(ctx) {
  const rows = ctx.state.integrationCatalog;
  return page(ctx, '设备与接口', '', null, table(ctx,{
    title:'设备与模型接口台账', rows,
    search:{placeholder:'搜索接口、编号或用途',value:r=>[r.title,r.id,r.group,r.description].join(' ')},
    filter:{label:'接口分类',all:'全部分类',value:r=>r.group},
    cols:[
      {label:'接口名称',view:r=>named(r.title,r.id)},
      {label:'分类',view:r=>r.group}, {label:'用途',view:r=>r.description},
      {label:'控制权限',view:r=>r.ownerOnly ? '仅 Owner' : '按机构授权'},
      {label:'接入状态',view:()=>badge(ctx,'预留端口','neutral')},
      {label:'操作',align:'end',view:r=>link(ctx,'查看接口',()=>inspectContract(ctx,r))},
    ],
  }));
}

export function renderGateways(route, ctx) {
  return route === 'integrations' ? integrations(ctx) : inbox(ctx);
}
