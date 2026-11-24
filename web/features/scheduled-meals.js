import { btn, named, node } from './shared.js';
import { residentAnchor, staffLabel } from './people-labels.js';

async function preview(payload, signal) {
  const response = await fetch('/api/scheduled-work/meals/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal,
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '无法读取今日伙食工单');
  return data;
}

function check(checked, disabled = false) {
  const input = node('input');
  input.type = 'checkbox';
  input.checked = checked;
  input.disabled = disabled;
  return input;
}

function mealRow(row) {
  const include = check(row.selected, Boolean(row.reason));
  const dishes = row.menu.map((name) => ({ name, choice: check(!row.omitted.includes(name), !row.selected) }));
  const details = node('details', 'group-intake-note', [
    node('summary', '', '核对吃了哪些菜'),
    node('div', 'scheduled-meal-dishes', dishes.map(({ name, choice }) =>
      node('label', 'group-person-check', [choice, name])
    )),
  ]);
  details.hidden = Boolean(row.reason);
  details.open = row.omitted.length > 0;
  const exceptions = node('p', 'fx-muted');
  const title = row.name + '（' + row.room + '）';
  const item = node('article', 'group-person', [
    node('div', '', [
      node('label', 'group-person-check', [include, named(title, row.place + ' · ' + row.bedLabel)]),
      row.reason ? node('small', 'fx-muted', row.reason) : exceptions,
    ]),
    details,
  ]);
  const omitted = () => dishes.filter(d => !d.choice.checked).map(d => d.name);
  function refresh() {
    dishes.forEach(d => { d.choice.disabled = !include.checked; });
    const skip = omitted();
    exceptions.textContent = !include.checked ? '' :
      (skip.length ? '没有吃 ' + skip.join('、') : '已勾选当餐全部菜品');
  }
  include.addEventListener('change', refresh);
  dishes.forEach(d => d.choice.addEventListener('change', refresh));
  refresh();
  return {item, include, title, row, omitted, refresh};
}


function signedMeals(ctx, receipts) {
  if (!receipts?.length) return null;
  return node('section', 'group-attendance', [
    node('h3', '', '已签认伙食'),
    node('div', 'group-person-list', receipts.map(row => {
      const account = {id: row.confirmedById, displayName: row.confirmedBy, role: row.confirmedByPosition};
      const label = residentAnchor(ctx, row.residentId, {eventId: row.eventId, day: row.day});
      if (label.textContent === '—') label.textContent = row.name + '（' + row.roomNumber + '）';
      return node('article', 'group-person scheduled-meal-receipt', [
        node('div', 'fx-profile', [
          label,
          node('p', '', row.intake ? '实际进食：' + row.intake : '当餐提供：' + row.details),
          node('small', 'fx-muted', [
            row.bedLabel,
            row.confirmedAt.replace('T', ' ').slice(0, 16),
            staffLabel(ctx, account) + ' 确认',
          ].filter(Boolean).join(' · ')),
        ]),
      ]);
    })),
  ]);
}

export function openScheduledMeal(ctx, source) {
  const content = node('div', 'fx-profile');
  const dialog = ctx.detail(source.occurrenceId ? '今日伙食批次' : '核对今日伙食', content);
  dialog.classList.add('group-dialog');
  let pending;

  function formFor(data) {
    const rows = data.rows.map(mealRow);
    const count = node('strong');
    const everyone = check(false);
    const submit = node('button', 'btn btn-primary', '核对并签认');
    submit.type = 'submit';
    const allMenus = [...new Set(data.rows.map(row => row.menu.join('、')))];
    const summary = node('p', '', allMenus.length === 1 ? allMenus[0] : '不同住户的菜品见逐人明细');
    const hint = node('p', 'fx-muted', '仅确认已核实的老人。取消某道菜的勾选，时间线会注明没有吃这道菜。');
    const form = node('form', 'group-editor', [
      node('div', 'group-area', [node('strong', '', data.day + ' · ' + data.kind), summary]),
      node('div', 'group-attendance-heading', [
        node('label', 'group-select-all', [everyone, '选中本批可签认人员']),
        count,
      ]),
      hint,
      node('div', 'group-person-list', rows.map(row => row.item)),
      node('footer', 'group-form-actions', [btn(ctx, '返回', () => dialog.close()), submit]),
    ]);
    function refresh() {
      const checked = rows.filter(r => r.include.checked && !r.include.disabled).length;
      const eligible = rows.filter(r => !r.include.disabled).length;
      count.textContent = '已核对 ' + checked + ' / ' + eligible + ' 人';
      everyone.checked = eligible > 0 && checked === eligible;
      everyone.indeterminate = checked > 0 && checked < eligible;
      submit.disabled = !checked;
    }
    everyone.addEventListener('change', () => {
      for (const row of rows) {
        if (row.include.disabled) continue;
        row.include.checked = everyone.checked;
        row.refresh();
      }
      refresh();
    });
    rows.forEach(row => row.include.addEventListener('change', refresh));
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (submit.disabled) return;
      const selected = rows.filter(r => r.include.checked && !r.include.disabled);
      const payload = {
        occurrenceId: data.occurrenceId, region: data.region, confirmed: true,
        entries: selected.map(({row, omitted}) => ({taskId: row.taskId, basis: row.basis, omitted: omitted()})),
      };
      const exceptions = selected.filter(r => r.omitted().length);
      const fields = [
        ['签认餐次', data.day + ' · ' + data.kind],
        ['签认人数', selected.length + ' 人'],
        ['没有吃的菜', exceptions.length
          ? exceptions.map(r => r.title + ' · ' + r.omitted().join('、')).join('；')
          : '所有选中的老人均吃了各自工单所列菜品'],
      ];
      submit.disabled = true;
      try {
        const saved = await ctx.command('care.confirmScheduledMeal', payload, {
          title: '确认伙食记录', target: data.kind, fields, expectedRevision: data.revision,
          confirmLabel: '确认并更新个人时间线', quiet: true,
        });
        if (saved) {
          if (dialog.open) dialog.close();
          openScheduledMeal(ctx.current?.() || ctx, {occurrenceId: data.occurrenceId, region: data.region});
        }
      } finally {
        refresh();
      }
    });
    refresh();
    return form;
  }

  async function load(input) {
    pending?.abort();
    const operation = new AbortController();
    pending = operation;
    content.replaceChildren(node('p', 'fx-muted', '正在核对伙食工单…'));
    try {
      const data = await preview(input, operation.signal);
      if (operation.signal.aborted || !dialog.open) return;
      if (data.choices) {
        content.replaceChildren(node('p', 'fx-muted', '今天有多批符合口述的伙食，请先选定一批。'),
          ...data.choices.map(item => btn(ctx, item.label, () => load({ ...input, taskId: item.taskId }))));
      } else {
        const current = ctx.current?.() || ctx;
        const signed = signedMeals(current, data.receipts);
        const header = !data.rows.length
          ? node('p', 'group-area', data.day + ' · ' + data.kind)
          : null;
        content.replaceChildren(...[header, signed, data.rows.length ? formFor(data) : null].filter(Boolean));
      }
    } catch (error) {
      if (operation.signal.aborted || !dialog.open) return;
      content.replaceChildren(node('p', 'form-error', error.message),
        btn(ctx, '查看照护工单手动核对', () => {
          dialog.close();
          ctx.go('care', 'tasks');
        }),
        btn(ctx, '重新读取', () => load(input)));
    }
  }

  dialog.addEventListener('close', () => pending?.abort());
  void load(source);
  return dialog;
}
