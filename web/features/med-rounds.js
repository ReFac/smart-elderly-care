import { btn, canAct, choose, facts, named, node, section } from './shared.js';

const label = (name, input) => node('label', 'field', [node('span', '', name), input]);

function selectControl(choices, current) {
  const control = node('select', 'fx-input');
  choices.forEach(([value, name]) => control.add(new Option(name, value)));
  control.value = current;
  return control;
}

async function preview(query) {
  const response = await fetch('/api/medication-rounds/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(query)
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '服药名单读取失败');
  return data;
}

export function parseBedCard(value) {
  const text = value.trim();
  try {
    const url = new URL(text);
    const params = new URLSearchParams(url.hash.slice(6));
    if (
      url.origin === location.origin &&
      url.hash.startsWith('#care?') &&
      /^\d{8}$/.test(params.get('bedcard') || '')
    )
      return { code: params.get('bedcard'), bed: params.get('bed') || '' };
  } catch {
    /* Printed EAN cards and handheld readers provide a code directly. */
  }
  const qr = /^AK1\|(\d{8})\|([^|]{1,80})$/.exec(text);
  return qr ? { code: qr[1], bed: qr[2] } : { code: text, bed: '' };
}

export function openLinkedBedCard(ctx) {
  if (!location.hash.startsWith('#care?')) return;
  const params = new URLSearchParams(location.hash.split('?')[1]);
  const code = params.get('bedcard');
  if (!code) return;
  history.replaceState(null, '', '#care');
  if (!/^\d{8}$/.test(code) || !canAct(ctx, 'care.confirmMedRound')) {
    ctx.toast('当前账号无法核对此床头卡。');
    return;
  }
  openMedicationRound(ctx, { cardCode: code, scannedBed: params.get('bed') || '' });
}

function receipt(record) {
  if (record.restricted)
    return node('p', 'fx-muted', '此人本时段已有签认，原床位凭证由当时房间的授权人员查阅。');
  return facts([
    ['核对结果', record.outcome === 'taken' ? '现场已观察到服药' : '未服，已提交护士复核'],
    ['签认人', record.actor + '（' + (record.position || '照护人员') + '）'],
    ['现场观察时间', record.observedTime || record.slot],
    ['签认时间', record.at.replace('T', ' ').slice(0, 19)],
    ['床位', record.room + ' · ' + record.bed],
    ['床头卡核验', record.checkedCardCode || '手动核对床位'],
    ['已登记执行的医嘱', record.medicationIds.length + ' 项'],
    ['备注', record.note || '无']
  ]);
}

export function openMedicationRound(ctx, source = {}) {
  if (!canAct(ctx, 'care.confirmMedRound')) return;
  const allowed = ['text', 'roomId', 'residentId', 'cardCode', 'slot', 'region'];
  let query = Object.fromEntries(Object.entries(source).filter(([key]) => allowed.includes(key)));
  let generation = 0;
  const body = node('div', 'fx-profile');
  let dialog = ctx.detail('床旁服药核对', body);
  const alive = () => dialog.isConnected && dialog.open;

  function showForm(data, index) {
    if (!alive()) return;
    const row = data.people[index];
    const options = data.availableSlots.map((s) => [s, s]);
    const slot = selectControl(options, row?.roundSlot || data.slot);
    slot.onchange = () => load({ ...query, slot: slot.value });
    const top = [label('核对时段 · ' + data.day, slot)];
    if (data.futureSlots.length)
      top.push(node('p', 'fx-attention', '尚未开始的时段不予签认：' + data.futureSlots.join('、')));
    if (query.text) top.unshift(node('p', 'fx-muted', '本次口述：' + query.text));
    if (!row) {
      const room = selectControl(
        [['', '请选择房间'], ...data.rooms.map((r) => [r.id, r.label])],
        ''
      );
      room.onchange = () => {
        if (room.value) load({ roomId: room.value, slot: slot.value });
      };
      body.replaceChildren(
        ...top,
        label('房间', room),
        node('p', 'fx-muted', '选择房间后，逐一核对每位老人的实际服药情况。')
      );
      return;
    }
    if (row.history?.length) {
      top.push(
        node('details', 'fx-profile', [
          node('summary', '', '查看近期服药签认（' + row.history.length + '）'),
          ...row.history.map((rec) =>
            node('details', 'fx-profile', [
              node(
                'summary',
                '',
                rec.day + ' · ' + rec.slot + ' · ' + (rec.outcome === 'taken' ? '已服' : '未服')
              ),
              receipt(rec)
            ])
          )
        ])
      );
    }
    const heading = node('div', 'fx-document-head', [
      node('span', 'fx-initial', ctx.ui.icon('pill', 20)),
      named(row.name + '（' + row.room + '）', row.location + ' · ' + row.bed + ' 床'),
      node('span', 'fx-muted', index + 1 + ' / ' + data.people.length + ' 项')
    ]);
    const next = () => {
      if (index + 1 < data.people.length) showForm(data, index + 1);
      else dialog.close();
    };
    const skip = btn(ctx, index + 1 < data.people.length ? '暂跳过，核对下一项' : '关闭', next);
    if (row.receipt) {
      body.replaceChildren(
        ...top,
        heading,
        section('此人本时段已签认', receipt(row.receipt)),
        choose(btn(ctx, index + 1 < data.people.length ? '下一项' : '完成查看', next, 'primary'))
      );
      return;
    }
    const status = selectControl(
      [
        ['taken', '已观察到服药'],
        ['notGiven', '未服药，提交护士复核']
      ],
      row.outcome
    );
    const observedTime = node('input', 'fx-input');
    observedTime.type = 'time';
    const note = node('textarea', 'fx-input');
    note.maxLength = 500;
    note.rows = 2;
    note.value = row.note;
    const noteLabel = label('现场备注', note);
    const choices = [];
    const orders = node('div', 'fx-profile');
    if (data.clinical && row.orders.length) {
      orders.append(node('strong', '', '逐项勾选亲自核实已服用的医嘱'));
      row.orders.forEach((order) => {
        const box = node('input');
        box.type = 'checkbox';
        choices.push([box, order.id]);
        orders.append(
          node('label', 'fx-toolbar', [
            box,
            named(
              order.name + ' · ' + order.scheduledAt.slice(11),
              [order.instruction, ...order.warnings].filter(Boolean).join(' · ')
            )
          ])
        );
      });
    } else {
      orders.append(
        node(
          'p',
          'fx-muted',
          data.clinical
            ? '此时段没有已到时且待执行的复核医嘱。本次签认只记录床旁观察。'
            : '本次签认记录您现场观察到的情况。医嘱执行由有临床权限的人员登记。'
        )
      );
    }
    const submit = node('button', 'btn btn-primary');
    submit.type = 'submit';
    const sync = () => {
      const missed = status.value === 'notGiven';
      noteLabel.firstChild.textContent = missed ? '未服原因（必填）' : '现场备注';
      note.required = missed;
      for (const [box] of choices) box.disabled = missed;
      submit.textContent = missed ? '确认未服并交护士复核' : '确认老人服药';
    };
    status.onchange = sync;
    sync();
    const form = node('form', 'fx-profile', [
      heading,
      label('实际情况', status),
      orders,
      label('实际观察时间（选填）', observedTime),
      noteLabel,
      node('p', 'fx-muted', '本次仅签认 ' + row.name + '，记录将使用当前登录人姓名。'),
      choose(skip, submit)
    ]);
    form.onsubmit = async (event) => {
      event.preventDefault();
      if (submit.disabled || !form.reportValidity()) return;
      submit.disabled = true;
      const payload = {
        residentId: row.residentId,
        basis: row.basis,
        day: data.day,
        slot: row.roundSlot,
        outcome: status.value,
        note: note.value.trim(),
        confirmed: true,
        medicationIds: choices
          .filter(([check]) => !check.disabled && check.checked)
          .map(([, id]) => id)
      };
      if (query.cardCode) payload.cardCode = query.cardCode;
      if (source.region) payload.region = source.region;
      if (observedTime.value) payload.observedTime = observedTime.value;
      const saved = await ctx.command('care.confirmMedRound', payload, {
        confirmed: true,
        quiet: true
      });
      if (!saved) {
        submit.disabled = false;
        return;
      }
      ctx.toast(row.name + '的服药核对已签认');
      if (index + 1 < data.people.length) {
        dialog = ctx.detail('床旁服药核对', body);
        showForm(data, index + 1);
      }
    };
    body.replaceChildren(...top, form);
  }

  async function load(nextQuery) {
    const ticket = ++generation;
    query = source.region ? { ...nextQuery, region: source.region } : nextQuery;
    body.replaceChildren(
      node('p', 'fx-muted', query.text ? '正在整理本次口述的房间和床位…' : '正在读取床位名单…')
    );
    try {
      const data = await preview(query);
      if (source.scannedBed && !data.people.every((p) => p.bed === source.scannedBed))
        throw new Error('二维码中的床位与当前床位不符，请重新核对床头卡。');
      if (ticket === generation) showForm(data, 0);
    } catch (error) {
      if (ticket === generation && alive())
        body.replaceChildren(
          node('p', 'form-error', error.message),
          choose(
            btn(ctx, '重新读取', () => load(nextQuery)),
            btn(ctx, '手动选房间', () => load({}))
          )
        );
    }
  }
  load(query);
  return dialog;
}

export function medicationRoundDesk(ctx) {
  return section(
    '本班服药核对',
    node('div', 'fx-profile', [
      node('p', 'fx-muted', '按房间逐位登记。未服药的原因会交给护士复核。'),
      choose(btn(ctx, '按房间核对', () => openMedicationRound(ctx), 'primary'))
    ])
  );
}
