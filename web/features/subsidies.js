import { badge, btn, choose, field, link, node } from './shared.js';
import { residentAnchor } from './people-labels.js';

const labels = { idFront: '身份证正面', idBack: '身份证反面', household: '户口本', invoice: '发票' };
const status = (row) => (row.claim ? '已生成清单' : row.missing.length ? '材料不全' : '材料齐全');

function selectControl(label, options) {
  const input = node('select');
  input.setAttribute('aria-label', label);
  for (const item of options) input.add(new Option(item, item));
  return input;
}
function label(text, control) {
  return node('label', 'subsidy-field', [node('span', '', text), control]);
}
function documentLink(item) {
  const a = node('a', 'subsidy-link', item.name);
  a.href = '/api/finance/subsidies/materials/' + item.id;
  a.target = '_blank';
  a.rel = 'noopener noreferrer';
  return a;
}

function printRows(ctx, month, list) {
  if (!list.length) return ctx.toast('请先勾选要打印的长辈');
  const stamp = new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' });
  const sheet = node('section', 'subsidy-print-sheet', [
    node('h1', '', month + ' 民政补贴申报材料清单'),
    node('p', '', [
      ctx.state.uiSettings.institutionName,
      ' · 经办人 ',
      ctx.state.user.displayName,
      ' · 打印于 ',
      stamp,
    ]),
    ...list.map((row) =>
      node('article', '', [
        node('h2', '', row.name + ' · ' + (row.bed || '床位未登记')),
        node('p', '', '入住 ' + row.admitted + '　' + row.type + '　' + status(row)),
        node(
          'p',
          '',
          row.claim ? '清单批次 ' + row.claim.batch + '　生成于 ' + row.claim.at.slice(0, 10) : '待核对材料',
        ),
        ...row.materials.map((m) =>
          node('p', '', [labels[m.kind], ' ', m.month, '　', m.name, '　', m.at.slice(0, 10)]),
        ),
        row.missing.length ? node('p', '', '待补材料：' + row.missing.join('、')) : null,
      ]),
    ),
  ]);
  document.body.append(sheet);
  try {
    window.print();
  } finally {
    sheet.remove();
  }
}

function upload(ctx, row, data, invoice) {
  const kinds = invoice ? ['invoice'] : ['idFront', 'idBack', 'household'];
  const kind = selectControl('材料类型', kinds);
  for (const o of kind.options) o.textContent = labels[o.value];
  const months = selectControl('发票所属月份', row.invoiceMonths);
  const file = node('input');
  file.type = 'file';
  file.accept = 'image/jpeg,image/png,application/pdf';
  file.required = true;
  const title = invoice ? '上传发票' : '维护证件';
  ctx.dialog({
    title: title + ' · ' + row.name,
    fields: [],
    submitLabel: '核对并留存',
    content: node('div', 'subsidy-fields', [
      label('材料类型', kind),
      invoice && label('发票月份', months),
      label('原件（PDF、PNG、JPEG，最大 8 MiB）', file),
    ]),
    onSubmit: async () => {
      const chosen = file.files[0];
      if (!chosen || !chosen.size || chosen.size > 8 * 1024 * 1024)
        throw Error('请选择 8 MiB 以内的非空原件');
      const base64 = await new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result.split(',')[1]);
        reader.onerror = () => reject(Error('原件无法读取，请重新选择'));
        reader.readAsDataURL(chosen);
      });
      return ctx.command(
        'ops.subsidyMaterial',
        {
          month: data.month,
          residentId: row.residentId,
          kind: kind.value,
          invoiceMonth: invoice ? months.value : '',
          fileName: chosen.name,
          imageBase64: base64,
        },
        {
          title,
          target: row.name,
          expectedRevision: data.revision,
          fields: [
            ['材料类型', labels[kind.value]],
            ['文件名', chosen.name],
            ['所属月份', invoice ? months.value : '长期证件'],
          ],
        },
      );
    },
  });
}

function viewRow(ctx, row, month) {
  const details = node('div', 'subsidy-details', [
    node('p', '', [row.name, '（', row.bed || '未分配床位', '）　', month, '　', row.type]),
    row.claim &&
      node(
        'p',
        '',
        '清单批次 ' +
          row.claim.batch.slice(0, 8) +
          ' · ' +
          row.claim.actor +
          ' · ' +
          row.claim.at.slice(0, 10),
      ),
    node('h3', '', '已留存材料'),
    ...row.materials.map((m) =>
      node('p', '', [
        labels[m.kind] + ' ' + m.month + '　',
        documentLink(m),
        '　',
        m.at.slice(0, 10),
        ' · ',
        m.actor,
      ]),
    ),
    !row.materials.length && node('p', 'fx-muted', '尚无留存原件'),
    row.missing.length > 0 && node('p', '', '待补材料：' + row.missing.join('、')),
    btn(ctx, '打印材料清单', () => printRows(ctx, month, [row])),
  ]);
  ctx.detail('申报材料 · ' + row.name, details);
}

export function subsidies(ctx) {
  const page = node('div', 'subsidy-page');
  const today = ctx.state.today;
  const month = node('input');
  month.type = 'month';
  month.max = today.slice(0, 7);
  const workspace = ctx.workspaceState || {};
  const filters = { month: today.slice(0, 7), ...workspace.subsidyFilters };
  month.value = filters.month;
  const states = selectControl('状态', ['全部状态', '材料不全', '材料齐全', '已生成清单']);
  const types = selectControl('申报类型', ['全部类型', '首次申报', '续报']);
  states.value = filters.status || '全部状态';
  types.value = filters.type || '全部类型';
  const building = selectControl('楼栋', []),
    floor = selectControl('楼层', []),
    room = selectControl('房间', []);
  const search = node('input');
  search.type = 'search';
  search.placeholder = '长辈姓名或床号';
  search.value = filters.query || '';
  const result = node('div', 'subsidy-result');
  const refresh = btn(
    ctx,
    '搜索',
    () => {
      pageIndex = 1;
      draw();
    },
    'primary',
  );
  const reset = btn(ctx, '重置', () => {
    states.selectedIndex = types.selectedIndex = 0;
    search.value = '';
    month.value = today.slice(0, 7);
    Object.assign(filters, { building: '', floor: '', room: '' });
    load();
  });
  page.append(
    node('section', 'subsidy-card', [
      node('h2', '', '民政补贴申报材料'),
      node('div', 'subsidy-filter', [
        label('申报月份', month),
        label('状态', states),
        label('申报类型', types),
        label('楼栋', building),
        label('楼层', floor),
        label('房间', room),
        label('关键字', search),
        choose(refresh, reset),
      ]),
    ]),
    result,
  );
  let data,
    sequence = 0,
    pageIndex = 1,
    pageSize = 20;
  const selected = new Set();
  function locations() {
    const rows = data?.rows || [];
    function options(el, list, key, caption, idKey, defaultLabel) {
      const choices = new Map(list.filter((r) => r[idKey]).map((r) => [r[idKey], caption(r)]));
      el.replaceChildren(
        new Option(defaultLabel, ''),
        ...[...choices]
          .sort((a, b) => a[1].localeCompare(b[1], 'zh-CN', { numeric: true }))
          .map(([id, text]) => new Option(text, id)),
      );
      el.value = choices.has(filters[key]) ? filters[key] : '';
      filters[key] = el.value;
    }
    options(building, rows, 'building', r => [r.campus, r.building].filter(Boolean).join(' / '), 'buildingId', '全部楼栋');
    const level = rows.filter((r) => !building.value || r.buildingId === building.value);
    options(floor, level, 'floor', r => [!building.value && r.campus, !building.value && r.building, r.floor].filter(Boolean).join(' / '), 'floorId', '全部楼层');
    options(
      room,
      level.filter((r) => !floor.value || r.floorId === floor.value),
      'room',
      r => [!building.value && r.campus, !building.value && r.building, !floor.value && r.floor, r.room].filter(Boolean).join(' / '),
      'roomId',
      '全部房间',
    );
  }
  for (const [input, key] of [
    [building, 'building'],
    [floor, 'floor'],
    [room, 'room'],
  ])
    input.onchange = () => {
      filters[key] = input.value;
      locations();
      pageIndex = 1;
      draw();
    };
  for (const el of [states, types])
    el.onchange = () => {
      pageIndex = 1;
      draw();
    };
  search.oninput = () => {
    pageIndex = 1;
    draw();
  };
  month.onchange = load;
  function rules() {
    ctx.dialog({
      title: '申报备料规则',
      description: '用于生成机构内部的材料清单，请按受理机构当期要求维护。',
      fields: [
        field('days', '正式入住满多少天纳入清单', {
          type: 'number',
          min: 1,
          max: 365,
          value: data.rules.minimumDays,
        }),
        field('months', '核对申报月之前几个整月的发票（仅在住月份）', {
          type: 'number',
          min: 0,
          max: 12,
          value: data.rules.invoiceMonths,
        }),
      ],
      onSubmit: (v) =>
        ctx.command(
          'ops.subsidyRules',
          { minimumDays: Number(v.days), invoiceMonths: Number(v.months) },
          {
            title: '保存申报规则',
            expectedRevision: data.revision,
            fields: [
              ['入住天数', v.days],
              ['前期发票月数', v.months],
            ],
          },
        ),
    });
  }
  function draw() {
    if (!data) return;
    const q = search.value.trim().toLowerCase();
    Object.assign(filters, { month: month.value, status: states.value, type: types.value, query: q });
    workspace.subsidyFilters = { ...filters };
    const rows = data.rows.filter(
      (r) =>
        (states.selectedIndex === 0 || status(r) === states.value) &&
        (types.selectedIndex === 0 || r.type === types.value) &&
        (!building.value || r.buildingId === building.value) &&
        (!floor.value || r.floorId === floor.value) &&
        (!room.value || r.roomId === room.value) &&
        (r.name + ' ' + r.bed + ' ' + r.room).toLowerCase().includes(q),
    );
    const visible = new Set(rows.map((r) => r.residentId));
    for (const id of selected) if (!visible.has(id)) selected.delete(id);
    const picked = rows.filter((r) => selected.has(r.residentId));
    const create = btn(
      ctx,
      '生成申报清单',
      () =>
        ctx.command(
          'ops.subsidyList',
          { month: data.month, residentIds: picked.map((r) => r.residentId) },
          {
            expectedRevision: data.revision,
            title: '生成申报清单',
            target: data.month,
            fields: [
              ['人数', String(picked.length)],
              ['材料', '保存本次核对的材料版本'],
            ],
          },
        ),
      'primary',
    );
    create.disabled = !picked.length || picked.some((r) => r.claim || r.missing.length);
    const print = btn(ctx, '批量打印', () => printRows(ctx, data.month, picked));
    print.disabled = !picked.length;
    const toolbar = node('header', 'subsidy-toolbar', [
      node('h3', '', '可申报长辈列表'),
      node(
        'small',
        '',
        `共 ${rows.length} 人 · 齐全 ${rows.filter((r) => !r.missing.length).length} · 待补 ${rows.filter((r) => r.missing.length).length} · 本月新增可申报 ${rows.filter((r) => r.eligibleMonth === data.month).length}`,
      ),
      choose(data.canConfigure && btn(ctx, '规则设置', rules), create, print),
    ]);
    const table = node('table', 'subsidy-grid'),
      countPages = Math.max(1, Math.ceil(rows.length / pageSize));
    pageIndex = Math.min(pageIndex, countPages);
    const slice = rows.slice((pageIndex - 1) * pageSize, pageIndex * pageSize);
    const all = node('input');
    all.type = 'checkbox';
    all.setAttribute('aria-label', '勾选本页全部长辈');
    all.disabled = !slice.length;
    all.checked = slice.length > 0 && slice.every((r) => selected.has(r.residentId));
    all.indeterminate = !all.checked && slice.some((r) => selected.has(r.residentId));
    all.onchange = () => {
      for (const r of slice) all.checked ? selected.add(r.residentId) : selected.delete(r.residentId);
      draw();
    };
    table.append(
      node(
        'thead',
        '',
        node(
          'tr',
          '',
          [
            all,
            '序号',
            '长辈姓名',
            '入住日期',
            '可申报月份',
            '身份证正反面',
            '户口本',
            '发票',
            '状态',
            '操作',
          ].map((t) => node('th', '', t)),
        ),
      ),
    );
    const body = node('tbody');
    for (const [i, r] of slice.entries()) {
      const check = node('input');
      check.type = 'checkbox';
      check.checked = selected.has(r.residentId);
      check.setAttribute('aria-label', '勾选' + r.name);
      check.onchange = () => {
        check.checked ? selected.add(r.residentId) : selected.delete(r.residentId);
        draw();
      };
      const cell = (ready, text) => badge(ctx, ready ? '已上传' : text, ready ? 'green' : 'amber');
      const invoices = r.missing.filter((m) => m.startsWith('发票'));
      const flags = choose(
        link(ctx, '查看', () => viewRow(ctx, r, data.month)),
        !r.claim && link(ctx, '维护证件', () => upload(ctx, r, data, false)),
        !r.claim && r.invoiceMonths.length > 0 && link(ctx, '上传发票', () => upload(ctx, r, data, true)),
        link(ctx, '打印', () => printRows(ctx, data.month, [r])),
      );
      const person = ctx.state.residents.find((p) => p.id === r.residentId);
      body.append(
        node(
          'tr',
          '',
          [
            check,
            (pageIndex - 1) * pageSize + i + 1,
            node('div', 'fx-named', [
              person ? residentAnchor(ctx, person) : r.name,
              node('small', '', [r.building, r.floor, r.bed].filter(Boolean).join(' · ')),
            ]),
            r.admitted,
            node('div', 'fx-named', [r.eligibleMonth, node('small', '', r.type)]),
            cell(!r.missing.some((m) => m.startsWith('身份证')), '待补'),
            cell(!r.missing.includes('户口本'), '未上传'),
            r.invoiceMonths.length
              ? cell(!invoices.length, '缺少 ' + invoices.map((m) => m.slice(3)).join('、'))
              : '本期无需提供',
            badge(ctx, status(r), r.missing.length ? 'amber' : 'green'),
            flags,
          ].map((v) => node('td', '', v)),
        ),
      );
    }
    table.append(body);
    const sizes = selectControl('每页条数', ['20', '50', '100']);
    sizes.value = String(pageSize);
    sizes.onchange = () => {
      pageSize = Number(sizes.value);
      pageIndex = 1;
      draw();
    };
    const prev = btn(ctx, '上一页', () => {
        pageIndex--;
        draw();
      }),
      next = btn(ctx, '下一页', () => {
        pageIndex++;
        draw();
      });
    prev.disabled = pageIndex === 1;
    next.disabled = pageIndex === countPages;
    result.replaceChildren(
      node('section', 'subsidy-card', [
        toolbar,
        node('div', 'subsidy-scroll', table),
        !rows.length && node('p', 'subsidy-empty', '没有匹配的申报记录'),
        node('footer', 'subsidy-pages', [
          node('small', '', `已选 ${selected.size} 人`),
          label('每页', sizes),
          prev,
          `${pageIndex} / ${countPages}`,
          next,
        ]),
      ]),
    );
  }
  async function load() {
    const id = ++sequence;
    selected.clear();
    data = null;
    pageIndex = 1;
    result.replaceChildren(node('p', 'subsidy-empty', '正在读取申报材料…'));
    try {
      if (!month.value || month.value > today.slice(0, 7)) throw Error('请选择当前月或以前的申报月份');
      const value = await ctx.get('/api/finance/subsidies?month=' + encodeURIComponent(month.value));
      if (sequence !== id) return;
      data = value;
      locations();
      draw();
    } catch (e) {
      if (sequence === id)
        result.replaceChildren(node('p', 'form-error', e.message), btn(ctx, '重新读取', load));
    }
  }
  load();
  return page;
}
