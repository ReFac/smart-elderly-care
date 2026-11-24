import { badge, btn, canAct, choose, facts, field, node, runForm, section } from './shared.js';

export function itemDetails(item) {
  return [item.brand, item.specification].filter(Boolean).join(' · ');
}

function optionalFields(item) {
  return [
    field('brand', '品牌（选填）', { required: false, maxLength: 80, value: item.brand }),
    field('specification', '容量、规格或型号（选填）', {
      required: false, maxLength: 80, value: item.specification,
      placeholder: '如 500 毫升、50 张/包、XL、KF-04',
    }),
  ];
}

function reviewFields(item) {
  return [
    ['品目名称', item.name],
    ['品牌', item.brand || '待登记'],
    ['容量 / 规格 / 型号', item.specification || '待登记'],
    ['库存单位', item.unit],
    ['库存下限', item.minimum + ' ' + item.unit],
    ['期初入库数量', item.openingQuantity + ' ' + item.unit],
  ];
}

async function preview(values) {
  const response = await fetch('/api/inventory/matches', {
    method: 'POST',
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(values),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '暂时无法核对相似品目');
  return data;
}

function confirmMatchedItem(ctx, values, result) {
  let modal;
  let pending = false;
  async function commit(action, payload) {
    if (pending) return;
    pending = true;
    try {
      if (await ctx.command(action, payload, { confirmed: true })) modal.close();
    } finally {
      pending = false;
    }
  }
  function goBack() {
    modal.close();
    addItem(ctx, values);
  }
  const candidates = result.matches.map((item) => {
    const relation = item.exact ? '相同品目'
      : item.relation === 'equivalent' ? '可能是同一品目' : '名称或用途相近';
    return section(item.name, node('div', 'fx-profile', [
      badge(ctx, relation, item.matchToken ? 'blue' : 'amber'),
      facts([
        ['品牌', item.brand || '待登记'],
        ['容量 / 规格 / 型号', item.specification || '待登记'],
        ['当前实存', item.quantity + ' ' + item.unit],
        ['库存下限', item.minimum + ' ' + item.unit],
      ]),
      item.matchToken && canAct(ctx, 'ops.mergeStockItem')
        ? choose(btn(ctx, '合并到此品目', () => commit('ops.mergeStockItem', {
            ...values, itemId: item.id, matchToken: item.matchToken,
          }), 'primary'))
        : node('p', 'form-description', item.blockedReason || '当前账号没有合并权限'),
    ]));
  });
  modal = ctx.detail('发现相似物资品目', node('div', 'fx-profile', [
    node('p', 'form-description', result.source === 'deepseek'
      ? 'DeepSeek 已核对候选，请检查包装和型号后选择。'
      : '已按库存台账匹配相近名称，请检查包装和型号后选择。'),
    section('本次填报', facts(reviewFields(values))),
    ...candidates,
    choose(
      btn(ctx, '返回修改', goBack),
      !result.exactExists ? btn(ctx, '仍然新建', () => commit('ops.addItem', values)) : null,
    ),
  ]));
}

export function addItem(ctx, item = {}) {
  const dialog = ctx.dialog({
    title: '建立物资品目',
    fields: [
      field('name', '物资名称', { maxLength: 80, value: item.name }),
      field('unit', '库存计量单位', { maxLength: 16, value: item.unit, placeholder: '如：盒、包、瓶' }),
      ...optionalFields(item),
      field('minimum', '库存下限', { type: 'number', min: 0, max: 999999999, step: 1, value: item.minimum || 0 }),
      field('openingQuantity', '期初入库数量', {
        type: 'number', required: false, min: 0, max: 999999999, step: 1, value: item.openingQuantity || 0,
      }),
    ],
    submitLabel: '核对相似品目',
    async onSubmit(values) {
      values.openingQuantity ||= '0';
      const result = await preview(values);
      if (!dialog.open) return;
      if (result.matches.length) {
        confirmMatchedItem(ctx, values, result);
        return true;
      }
      return ctx.command('ops.addItem', values, {
        title: '确认新建物资品目', target: values.name, fields: reviewFields(values),
      });
    },
  });
  return dialog;
}

export function editStockItem(ctx, item) {
  return runForm(ctx, {
    title: '编辑品牌和规格',
    description: item.name + ' · ' + item.unit,
    action: 'ops.editStockItem',
    fields: optionalFields(item),
    map: (values) => ({ ...values, itemId: item.id }),
    submitLabel: '确认修改',
  });
}
