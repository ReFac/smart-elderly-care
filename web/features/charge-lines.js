import { node, btn, money, records, named } from './shared.js';

function picker(options) {
  const control = node('select');
  for (const [value, label] of options) control.add(new Option(label, value));
  return control;
}
function number(min, step) {
  const el = node('input');
  el.type = 'number';
  el.min = min;
  el.step = step;
  el.required = true;
  return el;
}
const field = (label, el) => node('label', 'field', [node('span', '', label), el]);

export function chargesEditor(ctx, firstCategory) {
  const catalog = ctx.state.chargeCatalog;
  const rows = new Map(),
    list = node('div', 'invoice-rows');
  function append(initialCode) {
    const code = picker(Object.entries(catalog.categories));
    const unit = picker(catalog.units.map((x) => [x, x]));
    const basis = picker([
      ['presentDays', '按在院天数（扣请假）'],
      ['serviceDays', '按入住天数'],
      ['quantity', '填写实际数量'],
    ]);
    const qty = number(1, 1),
      rate = number(0, '0.01'),
      label = node('input');
    qty.value = 1;
    label.maxLength = 80;
    label.placeholder = '填写合同或凭证上的具体名称';
    const labelRow = field('约定项目名称', label),
      qtyRow = field('实际数量', qty);
    const row = node('div', 'invoice-row', [
      field('费用类别', code),
      field('数量依据', basis),
      field('单位', unit),
      qtyRow,
      field('约定单价（元）', rate),
      labelRow,
      btn(
        ctx,
        '移除费用项',
        () => {
          rows.delete(row);
          row.remove();
        },
        'ghost',
      ),
    ]);
    function sync() {
      qtyRow.hidden = qty.disabled = basis.value !== 'quantity';
      unit.disabled = qty.disabled;
      if (unit.disabled) unit.value = '天';
      labelRow.hidden = label.disabled = code.value !== 'other';
      label.required = !label.disabled;
    }
    code.onchange = () => {
      basis.value = code.value === 'meal' ? 'presentDays' : 'quantity';
      unit.value = code.value === 'meal' ? '天' : '笔';
      sync();
    };
    basis.onchange = sync;
    if (typeof initialCode === 'string' && catalog.categories[initialCode]) {
      code.value = initialCode;
      code.onchange();
    } else sync();
    rows.set(row, () => ({
      code: code.value,
      unit: unit.value,
      basis: basis.value,
      unitPrice: rate.value,
      ...(qty.disabled ? {} : { quantity: qty.value }),
      ...(label.disabled ? {} : { label: label.value }),
    }));
    list.append(row);
  }
  if (firstCategory) append(firstCategory);
  return {
    element: node('section', 'fx-section', [
      node('h3', '', '饮食及其他费用'),
      list,
      btn(ctx, '添加费用项', append),
    ]),
    read: () => [...rows.values()].map((f) => f()),
  };
}

export function billedLines(bill) {
  if (bill.lineItems) return bill.lineItems;
  const known = [
    ['bedTotal', '房间床位费'],
    ['careTotal', '护理费'],
    ['packageFee', '套餐费'],
  ]
    .filter(([k]) => bill[k] != null)
    .map(([k, label]) => ({ label, amount: bill[k] }));
  const remainder =
    Math.round((bill.amount - known.reduce((a, row) => a + row.amount, 0)) * 100) / 100;
  if (remainder || !known.length) known.push({ label: '历史账单未细分金额', amount: remainder });
  return known;
}

export const lineDescription = (row) =>
  [
    row.start ? row.start + ' 至 ' + row.end : '',
    row.unit ? row.quantity + ' ' + row.unit + ' × ' + money(row.unitPrice) : '',
    money(row.amount),
  ]
    .filter(Boolean)
    .join(' · ');

export const feeLedger = (bill) =>
  records(billedLines(bill), (row) => named(row.label, lineDescription(row)));
