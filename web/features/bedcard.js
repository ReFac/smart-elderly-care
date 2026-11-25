import { printResidentSheet } from './resident-print.js';
import { openMedicationRound, parseBedCard } from './med-rounds.js';
import { residentLabel, staffLabel } from './people-labels.js';
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
function assignments(ctx) {
  return new Map(Object.entries(ctx.state.currentBedCards || {}));
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

export function hasBedCard(ctx, resident) {
  const card = ctx.state.currentBedCards?.[resident.id];
  return Boolean(resident.status === '在住' && resident.bedId && card?.bedId === resident.bedId &&
    /^\d{8}$/.test(card.code) && ctx.state.beds.some(bed => bed.id === resident.bedId && bed.residentId === resident.id));
}

function cardContent(ctx, resident) {
  const assignment = ctx.state.currentBedCards[resident.id];
  const bed = ctx.state.beds.find(row => row.id === resident.bedId);
  const qr = node('img');
  qr.src = '/api/medication-rounds/cards/' + assignment.code + '.png';
  qr.alt = bed.label + ' 床核验二维码';
  qr.width = qr.height = 140;
  return node('article', 'fx-bedcard', [
    node('header', 'fx-bedcard-head', [
      node('span', '', '床旁身份核验'),
      node('span', '', bed.ward)
    ]),
    node('h3', '', residentLabel(ctx, resident)),
    node('p', '', [bed.label + ' 床', resident.level].filter(Boolean).join(' · ')),
    node('div', 'fx-card-barcode', [qr, barcode(assignment.code), node('strong', '', assignment.code)])
  ]);
}

export async function printBedCards(ctx, ids) {
  const live = ctx.current?.() || ctx;
  const people = new Map(live.state.residents.map(row => [row.id, row]));
  const selected = [...new Set(ids)].map(id => people.get(id));
  if (!selected.length || selected.some(row => !row || !hasBedCard(live, row))) {
    ctx.toast('请选择仍有有效床头卡的在住长辈，核对床位后重试。');
    return;
  }
  const styles = `    main {display:grid;grid-template-columns:repeat(2, 88mm);gap:5mm;}
    article {break-inside:avoid;box-sizing:border-box;border:1px solid #536580;border-top:1.5mm solid #1c3557;}
    header {display:flex;justify-content:space-between;padding:2mm 3mm;border-bottom:1px solid #bfc5d1;}
    h3 {margin:2mm 3mm 0;font-size:19px;} p {margin:0 3mm 2mm;}
    .fx-card-barcode {border-top:1px dashed #999;display:grid;justify-items:center;align-items:center;padding:2mm;}
    .fx-card-barcode img {width:28mm;height:28mm;} svg {width:48mm;height:9mm;} strong {font:14px monospace;}
    footer {padding:2mm 3mm;color:#555;font-size:10px;}`;
  const cards = node('main');
  const printedBy = staffLabel(live, live.state.user);
  for (const person of selected) {
    const card = cardContent(live, person);
    const footer = node('footer');
    footer.textContent = [today(live), printedBy].join(' · ');
    card.append(footer);
    cards.append(card);
  }
  return printResidentSheet(live, '床头卡', cards, styles, '未能载入全部床位二维码，请刷新名册后重试。');
}

export function bedCard(ctx, resident) {
  if (!hasBedCard(ctx, resident)) {
    ctx.toast('长辈当前没有有效床头卡。');
    return;
  }
  const card = cardContent(ctx, resident);
  ctx.detail(
    '床头卡',
    node('div', 'fx-profile', [
      card,
      choose(
        btn(ctx, '打印床头卡', () => printBedCards(ctx, [resident.id])),
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
  input.maxLength = 512;
  input.required = true;
  input.placeholder = '扫码，或输入 8 位床头卡编号';
  input.autocomplete = 'off';
  const label = node('label', 'field', [node('span', '', '扫描二维码、条码或输入卡号'), input]);
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
    const scan = parseBedCard(input.value);
    const code = scan.code;
    const entry = [...assignments(ctx)].find(([, entry]) => entry.code === code);
    const person =
      entry &&
      ctx.state.residents.find(
        (r) => r.id === entry[0] && r.status === '在住' && r.bedId === entry[1].bedId
      );
    const bed =
      person && ctx.state.beds.find((b) => b.id === person.bedId && b.residentId === person.id);
    if (!bed || (scan.bed && bed.label !== scan.bed)) {
      result.textContent = '未找到有效的在住分配，请核对床头卡。';
      return;
    }
    const tasks = ctx.state.tasks
      .filter((t) => t.residentId === person.id && t.date === today(ctx) && t.status === '待执行')
      .sort((a, b) => a.time.localeCompare(b.time));
    add(
      result,
      facts([
        ['长辈', residentLabel(ctx, person)],
        ['当前床位', `${bed.ward} · ${bed.label}`]
      ]),
      canAct(ctx, 'care.confirmMedRound')
        ? btn(ctx, '按此床头卡核对服药', () => openMedicationRound(ctx, {cardCode:code}), 'primary')
        : null,
      section(
        '今日待执行',
        records(
          tasks,
          (task) =>
            node('div', 'fx-toolbar', [
              named(task.title, `${task.time} · ${staffLabel(ctx, task.assignee, task.assigneeId)}`),
              btn(ctx, '登记执行', () => {
                runForm(ctx, {
                  title: '床旁执行',
                  action: 'care.completeTask',
                  description: `${residentLabel(ctx, person)} · ${bed.label} · ${task.title}`,
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
        `${residentLabel(ctx, resident)}的已完成服务`,
        records(
          events,
          (event) => named(event.title, `${event.date} · ${event.kind}`),
          '暂无已完成的服务。'
        )
      )
    ])
  );
}
