import {
  canAct,
  hasGrant,
  add,
  btn,
  choose,
  facts,
  memo,
  named,
  node,
  records,
  runForm,
  section,
  today
} from './shared.js';
// Early draft workspaces have an append-only bed ledger without a stored card code.
// The server uses the same EAN-8 fallback for those existing allocations.
function legacyCardCode(sequence) {
  const digits = String(2000000 + sequence);
  const sum = [...digits].reduce(
    (total, digit, index) => total + Number(digit) * (index % 2 ? 1 : 3),
    0
  );
  return digits + ((10 - (sum % 10)) % 10);
}

function assignments(ctx) {
  const current = new Map();
  ctx.state.bedMoves.forEach((move, index) => {
    if (move.bedId)
      current.set(move.residentId, {
        bedId: move.bedId,
        code: move.cardCode || legacyCardCode(index + 1)
      });
    else current.delete(move.residentId);
  });
  return current;
}

const leftDigits = [
  '0001101',
  '0011001',
  '0010011',
  '0111101',
  '0100011',
  '0110001',
  '0101111',
  '0111011',
  '0110111',
  '0001011'
];

export function barcodeBits(code) {
  if (!/^\d{8}$/.test(code)) throw new Error('床头卡编号格式错误');
  const left = [...code.slice(0, 4)].map((n) => leftDigits[n]).join('');
  const right = [...code.slice(4)]
    .map((n) => leftDigits[n])
    .join('')
    .replace(/[01]/g, (value) => (value === '1' ? '0' : '1'));
  return '101' + left + '01010' + right + '101';
}

function barcode(code) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  const bits = barcodeBits(code);
  svg.setAttribute('width', '240');
  svg.setAttribute('height', '90');
  svg.setAttribute('viewBox', `0 0 ${bits.length + 20} 32`);
  svg.setAttribute('aria-label', `床头卡条码 ${code}`);
  svg.setAttribute('role', 'img');
  svg.style.maxWidth = '100%';
  const background = document.createElementNS(ns, 'rect');
  background.setAttribute('width', '100%');
  background.setAttribute('height', '100%');
  background.setAttribute('fill', 'white');
  svg.append(background);
  for (const match of bits.matchAll(/1+/g)) {
    const bar = document.createElementNS(ns, 'rect');
    bar.setAttribute('x', String(10 + match.index));
    bar.setAttribute('width', String(match[0].length));
    bar.setAttribute('height', '31');
    bar.setAttribute('fill', 'black');
    svg.append(bar);
  }
  return svg;
}

function printCard(ctx, card) {
  const sheet = window.open('', '_blank', 'popup,width=540,height=540');
  if (!sheet) {
    ctx.toast('请允许此站点打开床头卡打印窗口。');
    return;
  }
  sheet.opener = null;
  const doc = sheet.document;
  doc.documentElement.lang = 'zh-CN';
  doc.title = '打印床头卡';
  const style = doc.createElement('style');
  style.textContent = `@page { margin: 12mm; }
    body { margin: 0; color: #182843; font: 16px/1.5 sans-serif; }
    article { box-sizing: border-box; width: 90mm; max-width: 100%; border: 1px solid #536580; border-top: 1.5mm solid #1c3557; }
    header { display:flex; justify-content:space-between; padding:2mm 4mm; border-bottom:1px solid #bfc5d1; }
    h3 { margin: 3mm 4mm 0; font-size: 22px; } p { margin:0 4mm 3mm; }
    .fx-card-barcode { border-top:1px dashed #a6823b; text-align:center; padding:3mm; }
    svg, strong { display:block; margin:auto; } strong { font: bold 17px monospace; letter-spacing:.18em; }`;
  doc.head.append(style);
  doc.body.append(doc.importNode(card, true));
  sheet.addEventListener('afterprint', () => sheet.close(), {
    once: true
  });
  sheet.focus();
  sheet.print();
}

export function bedCard(ctx, resident) {
  const assignment = assignments(ctx).get(resident.id);
  const bed = ctx.state.beds.find(
    (row) => row.id === resident.bedId && row.residentId === resident.id
  );
  if (!bed || !assignment || assignment.bedId !== bed.id || resident.status !== '在住') {
    ctx.toast('长者当前没有有效床头卡。');
    return;
  }
  const card = node('article', 'fx-bedcard', [
    node('header', 'fx-bedcard-head', [
      node('span', '', '床旁身份核验'),
      node('span', '', bed.ward)
    ]),
    node('h3', '', resident.name),
    node('p', '', [bed.label + ' 床', resident.level].filter(Boolean).join(' · ')),
    node('div', 'fx-card-barcode', [barcode(assignment.code), node('strong', '', assignment.code)])
  ]);
  ctx.detail(
    '床头卡',
    node('div', 'fx-profile', [
      card,
      choose(
        btn(ctx, '打印床头卡', () => printCard(ctx, card)),
        canAct(ctx, 'care.completeTask')
          ? btn(ctx, '床旁核验', () => bedside(ctx), 'primary')
          : null
      )
    ])
  );
}

export function bedside(ctx) {
  if (!canAct(ctx, 'care.completeTask')) return;
  const input = node('input', 'fx-input');
  input.type = 'text';
  input.inputMode = 'numeric';
  input.maxLength = 8;
  input.required = true;
  input.placeholder = '8 位床头卡编号';
  input.autocomplete = 'off';
  const label = node('label', 'field', [node('span', '', '扫描条码或输入卡号'), input]);
  const submit = node('button', 'btn btn-primary', '核验床头卡');
  submit.type = 'submit';
  const form = node('form', 'fx-profile fx-scan-panel', [
    node('div', 'fx-document-head', [
      node('span', 'fx-initial', ctx.ui.icon('bed', 20)),
      named('床旁身份核验', '核对床头卡后查看今日任务')
    ]),
    label,
    choose(submit)
  ]);
  const result = node('div', 'fx-profile');
  result.setAttribute('aria-live', 'polite');
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    result.replaceChildren();
    const code = input.value.trim();
    const entry = [...assignments(ctx)].find(([, entry]) => entry.code === code);
    const person =
      entry &&
      ctx.state.residents.find(
        (r) => r.id === entry[0] && r.status === '在住' && r.bedId === entry[1].bedId
      );
    const bed =
      person && ctx.state.beds.find((b) => b.id === person.bedId && b.residentId === person.id);
    if (!bed) {
      result.textContent = '未找到有效的在住分配，请核对床头卡。';
      return;
    }
    const tasks = ctx.state.tasks
      .filter((t) => t.residentId === person.id && t.date === today(ctx) && t.status === '待执行')
      .sort((a, b) => a.time.localeCompare(b.time));
    add(
      result,
      facts([
        ['长者', person.name],
        ['当前床位', `${bed.ward} · ${bed.label}`]
      ]),
      section(
        '今日待执行',
        records(
          tasks,
          (task) =>
            node('div', 'fx-toolbar', [
              named(task.title, `${task.time} · ${task.assignee}`),
              btn(ctx, '登记执行', () => {
                runForm(ctx, {
                  title: '床旁执行',
                  action: 'care.completeTask',
                  description: `${person.name} · ${bed.label} · ${task.title}`,
                  fields: [memo('note', '执行记录')],
                  map: (values) => ({
                    ...values,
                    taskId: task.id,
                    bedId: bed.id,
                    cardCode: code
                  }),
                  submitLabel: '确认完成'
                });
              })
            ]),
          '今日工单均已处理或尚未排入任务。'
        )
      )
    );
  });
  input.addEventListener('input', () => result.replaceChildren());
  ctx.detail('床旁核验', node('div', 'fx-profile', [form, result]));
  input.focus();
}

export function familyPreview(ctx, resident) {
  if (!hasGrant(ctx, 'care', 'clinical')) return;
  const events = ctx.state.tasks
    .filter((task) => task.residentId === resident.id && task.status === '已完成')
    .map((task) => ({
      date: task.completedAt || task.date,
      title: task.title,
      kind: task.kind
    }));
  for (const med of ctx.state.medications.filter(
    (m) => m.residentId === resident.id && m.status === '已执行'
  )) {
    events.push({
      date: med.executedAt || med.date,
      title: '用药服务已执行',
      kind: med.name
    });
  }
  events.sort((a, b) => b.date.localeCompare(a.date));
  ctx.detail(
    '服务记录预览',
    node('div', 'fx-profile', [
      node('p', 'fx-muted', '按当前员工的岗位权限展示已完成服务。'),
      section(
        `${resident.name}的已完成服务`,
        records(
          events,
          (event) => named(event.title, `${event.date} · ${event.kind}`),
          '暂无已完成的服务。'
        )
      )
    ])
  );
}
