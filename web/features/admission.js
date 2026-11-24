import {
  node,
  btn,
  badge,
  field,
  select,
  options,
  choose,
  table,
  today,
  canAct,
} from './shared.js';
import { profile } from './residency.js';

const statuses = { 未入住: '未入住', 在住: '在住', 已退住: '归档老人' };
export const statusLabel = (row) => statuses[row.status] || row.status;
const archived = (row) => row.status === '已退住';

export function register(ctx, inquiry) {
  const notify = node('div', 'admission-match');
  notify.setAttribute('aria-live', 'polite');
  const day = today(ctx);
  const oldest = new Date(day + 'T00:00:00Z');
  oldest.setUTCDate(oldest.getUTCDate() - 364);
  const dialog = ctx.dialog({
    title: '新建长者档案',
    content: notify,
    fields: [
      field('name', '姓名', { value: inquiry?.name || '', maxLength: 60 }),
      select('kind', '档案类别', [
        { value: 'new', label: '新档案 · 等待入住' },
        { value: 'archive', label: '归档老人 · 仅保管资料' },
      ]),
      ...(ctx.state.campusOptions?.length
        ? [
            select(
              'campusId',
              '建档分院',
              ctx.state.campusOptions.map((c) => ({ value: c.id, label: c.name })),
              { value: inquiry?.campusId }
            ),
          ]
        : []),
      select('gender', '性别', options(['未登记', '女', '男'])),
      select(
        'age',
        '年龄',
        [
          { value: '', label: '未登记' },
          ...Array.from({ length: 126 }, (_, i) => ({ value: String(i), label: i + ' 岁' })),
        ],
        { required: false }
      ),
      field('archiveDate', '原退住或归档日期', {
        type: 'date',
        value: day,
        min: oldest.toISOString().slice(0, 10),
        max: day,
        required: false,
      }),
    ],
    submitLabel: '建立档案',
    onSubmit: (v) => {
      const payload = { ...v, name: v.name.trim() };
      if (!payload.age) delete payload.age;
      if (v.kind !== 'archive') delete payload.archiveDate;
      if (inquiry) payload.inquiryId = inquiry.id;
      const same = matching(payload.name);
      if (same.length) payload.acknowledgeArchive = true;
      return ctx.command('care.register', payload, {
        title: same.length ? '核实与归档老人的身份并建立独立档案' : '建立长者档案',
        target: payload.name,
        fields: [
          ['类别', v.kind === 'archive' ? '归档老人，保管 365 天' : '未入住，建档后可分床'],
          ...(same.length ? [['同名归档', same.map((x) => x.name + ' · ' + x.id).join('、')]] : []),
          ...(v.kind === 'archive' ? [['归档日期', v.archiveDate || day]] : []),
        ],
      });
    },
  });
  function matching(name) {
    return ctx.state.residents.filter((r) => archived(r) && r.name === name.trim());
  }
  const controls = dialog.querySelector('form').elements;
  const show = () => {
    controls.archiveDate.closest('label').hidden = controls.kind.value !== 'archive';
    controls.archiveDate.disabled = controls.kind.value !== 'archive';
    const rows = matching(controls.name.value);
    notify.replaceChildren();
    if (rows.length) {
      notify.append(
        node('strong', '', '发现同名归档老人，请核对档案号。'),
        ...rows.map((r) =>
          btn(
            ctx,
            r.name + ' · ' + (r.dischargedAt || '历史归档') + ' · 查看档案',
            () => profile(ctx, r),
            'ghost'
          )
        )
      );
    }
  };
  controls.kind.onchange = show;
  controls.name.oninput = show;
  show();
  controls.name.focus();
}

function bedLabel(ctx, id) {
  const bed = ctx.state.beds.find((b) => b.id === id);
  const place = ctx.state.bedLocations?.[id];
  return bed ? [...(place || [bed.ward]), bed.label].filter(Boolean).join(' / ') : '—';
}

export function allocate(ctx, person, targetBed) {
  if (!person) {
    ctx.detail('选择长者档案', registry(ctx, { bed: targetBed }));
    return;
  }
  if (archived(person)) {
    profile(ctx, person);
    return;
  }
  const transfer = person.status === '在住';
  const free = ctx.state.beds.filter((b) => b.status === '空闲' && !b.residentId);
  if (!free.length) {
    ctx.toast('当前范围暂无可分配的空闲床位');
    return;
  }
  const action = transfer ? 'care.transfer' : 'care.admit';
  ctx.dialog({
    title: transfer ? '转移床位' : '从档案办理入住',
    description:
      person.name +
      ' · 档案 ' +
      person.id +
      (transfer ? ' · 当前床位 ' + bedLabel(ctx, person.bedId) : ''),
    fields: [
      select(
        'bedId',
        transfer ? '新床位' : '入住床位',
        free.map((b) => ({ value: b.id, label: bedLabel(ctx, b.id) })),
        { value: targetBed?.id }
      ),
      ...(!transfer
        ? [
            select('level', '照护等级', options(['自理', '半失能', '失能']), {
              value: person.level,
            }),
            field('endDate', '合同到期日', { type: 'date', min: today(ctx), required: false }),
          ]
        : []),
    ],
    submitLabel: transfer ? '核对转床' : '核对入住',
    onSubmit: (values) => {
      const payload = { residentId: person.id, ...values };
      if (transfer) payload.fromBedId = person.bedId;
      if (!values.endDate) delete payload.endDate;
      const fields = transfer
        ? [
            ['原床位', bedLabel(ctx, person.bedId)],
            ['新床位', bedLabel(ctx, payload.bedId)],
            ['床位变动', '确认后立即释放原床位并登记新床位。'],
          ]
        : [
            ['长者档案', person.name + ' · ' + person.id],
            ['入住床位', bedLabel(ctx, payload.bedId)],
            ['照护等级', payload.level],
            ['合同到期', payload.endDate || '入住日起 365 天'],
          ];
      return ctx.command(action, payload, {
        title: transfer ? '确认将' + person.name + '从原床位转至新床位？' : '确认从档案办理入住',
        target: person.name,
        fields,
        confirmLabel: transfer ? '确认转床' : '确认入住',
      });
    },
  });
}

export function registry(ctx, { bed = null } = {}) {
  const panel = node('div', 'admission-registry');
  const search = node('input', 'fx-input');
  search.type = 'search';
  search.placeholder = '搜索所有档案的姓名、姓氏或档案号';
  search.setAttribute('aria-label', search.placeholder);
  const body = node('div'),
    scope = node('small', 'fx-muted'),
    toggle = node('button', 'btn btn-ghost admission-all');
  toggle.type = 'button';
  let all = false;
  function draw() {
    const term = search.value.trim().normalize('NFKC').toLocaleLowerCase();
    const people = [...ctx.state.residents]
      .reverse()
      .filter((r) =>
        term
          ? (r.name + ' ' + r.id).normalize('NFKC').toLocaleLowerCase().includes(term)
          : all || r.status === '未入住'
      );
    scope.textContent = term ? '搜索范围 · 全部档案' : all ? '全部档案' : '待入住的新档案';
    toggle.hidden = !!term;
    toggle.textContent = all ? '仅查看待入住新档案' : '查看全部档案（含在住及归档老人）';
    body.replaceChildren(
      table(ctx, {
        title: term ? '搜索结果' : all ? '全部档案' : '待入住档案',
        rows: people,
        empty: term
          ? '没有找到匹配档案，可尝试姓名中的一个字。'
          : all
            ? '暂无长者档案。'
            : '暂无待入住档案，可新建档案或查看下方全部档案。',
        cols: [
          {
            label: '长者',
            view: (r) =>
              node('div', 'fx-named', [node('strong', '', r.name), node('small', '', r.id)]),
          },
          { label: '状态', view: (r) => badge(ctx, statusLabel(r)) },
          {
            label: '床位 / 归档日期',
            view: (r) => (r.bedId ? bedLabel(ctx, r.bedId) : r.dischargedAt || '—'),
          },
          {
            label: '操作',
            align: 'end',
            view: (r) =>
              choose(
                !archived(r) && canAct(ctx, r.status === '在住' ? 'care.transfer' : 'care.admit')
                  ? btn(
                      ctx,
                      r.status === '在住' ? '转床' : '办理入住',
                      () => allocate(ctx, r, bed),
                      'ghost'
                    )
                  : null,
                btn(ctx, '查看档案', () => profile(ctx, r), 'ghost')
              ),
          },
        ],
      })
    );
  }
  search.oninput = draw;
  toggle.onclick = () => {
    all = !all;
    draw();
  };
  panel.append(node('div', 'admission-search', [search, scope]), body, toggle);
  draw();
  return panel;
}

export function historicInquiries(ctx) {
  const items = ctx.state.inquiries.filter((q) => q.status === '待跟进' && !q.residentId);
  if (!canAct(ctx, 'care.register') || !items.length) return null;
  const rows = items.map((i) =>
    node('li', '', [
      node('span', '', i.name + ' · ' + i.date),
      btn(ctx, '以咨询建档', () => register(ctx, i), 'ghost'),
    ])
  );
  return node('details', 'fx-disclosure', [
    node('summary', 'fx-disclosure-head', '待关联的历史入住咨询（' + items.length + '）'),
    node('ul', 'fx-records', rows),
  ]);
}
