import { residentLabel, residentAnchor, staffLabel } from './people-labels.js';
import { node, page, table, btn, badge, facts, records, section, named, today } from './shared.js';
import {
  loadProfileChoices,
  regionPicker,
  picker,
  textControl,
  group,
} from './profile-controls.js';

function history(ctx, person, rows) {
  ctx.detail(
    residentLabel(ctx, person) + ' · 长护险办理凭证',
    records([...rows].reverse(), (e) =>
      section(
        e.date + ' · ' + e.event,
        facts(
          [
            ['办理结果', e.displayStatus],
            ['参保统筹地区', e.regionLabel],
            ['参保险种', e.insuranceType],
            ['正式文书编号', e.reference],
            ['评估等级', e.grade],
            ['核定服务方式', e.service],
            ['待遇起止', e.startsOn ? [e.startsOn, e.endsOn || '文书未列截止日'].join(' 至 ') : ''],
            ['文书补充', e.note],
            ['登记者', staffLabel(ctx, e.operator)],
          ].filter(([, v]) => v),
        ),
      ),
    ),
  );
}

const currentResidents = ctx => (ctx.state.residents || []).filter((p) => ['在住', '未入住', '待入住', '新档案'].includes(p.status));

export async function registerLongCare(ctx, people = currentResidents(ctx), initial) {
  if (!people.length) return ctx.toast('当前没有可登记长护险的长辈');
  let regions;
  try {
    ({ regions } = await loadProfileChoices());
  } catch (e) {
    ctx.toast(e.message);
    return;
  }
  const catalog = ctx.state.longCareCatalog;
  const roster = node('select');
  roster.required = true;
  roster.add(new Option('选择已建档的长辈', ''));
  for (const r of people) roster.add(new Option(residentLabel(ctx, r) + ' · ' + r.id, r.id));
  roster.value = initial || '';
  const insurance = picker('参保险种（据参保凭证）', catalog.insuranceTypes || []);
  const stage = picker('办理事项', [], '', true);
  const day = textControl('经办日期', today(ctx), 'date', { required: true, max: today(ctx) });
  const ref = textControl('正式文书或受理编号', '', 'text', { required: true, maxLength: 100 });
  const grade = picker('评估等级（按结论书）', catalog.grades);
  const service = picker('护理服务方式（按核定文书）', catalog.services);
  const starts = textControl('待遇起始日', '', 'date');
  const ends = textControl('待遇截止日（文书载明时填写）', '', 'date');
  const note = textControl('文书补充', '', 'textarea', { rows: 2, maxLength: 300 });
  const where = node('div');
  let region, last;
  function sync() {
    const event = stage.control.value;
    const graded = ['登记评估结论', '补录已核定待遇'].includes(event);
    const approved = ['登记待遇核定', '补录已核定待遇'].includes(event);
    for (const [item, show] of [
      [grade, graded],
      [service, approved],
      [starts, approved],
      [ends, approved],
    ]) {
      item.element.hidden = !show;
      item.control.disabled = !show;
      item.control.required = show && item !== ends;
    }
    note.control.required =
      (graded && grade.control.value === '其他书面等级') ||
      (approved && service.control.value === '其他核定方式');
    ends.control.min = starts.control.value;
  }
  function update() {
    last = (ctx.state.longCareEvents || []).filter((e) => e.residentId === roster.value).at(-1);
    stage.control.replaceChildren(new Option('请选择', ''));
    if (roster.value)
      for (const value of catalog.stages[last?.status || ''])
        stage.control.add(new Option(value, value));
    region = regionPicker(regions, '参保统筹地区', last?.region, '', true);
    where.replaceChildren(region.element);
    insurance.control.value = last?.insuranceType || '';
    day.control.min = last?.date || '';
    sync();
  }
  roster.onchange = update;
  stage.control.onchange = sync;
  grade.control.onchange = sync;
  service.control.onchange = sync;
  starts.control.onchange = sync;
  update();
  ctx.dialog({
    title: '登记长护险办理',
    fields: [],
    content: node('div', 'dossier-form', [
      group('经办资料', [
        node('label', 'field', [node('span', '', '长辈档案'), roster]),
        stage.element,
        insurance.element,
        day.element,
        ref.element,
      ]),
      where,
      group('核定资料', [
        grade.element,
        service.element,
        starts.element,
        ends.element,
        note.element,
      ]),
      node('p', 'fx-muted', '按参保地经办机构的文书登记。系统保留每一步的办理记录和登记者。'),
    ]),
    onSubmit: () => {
      const place = region.read() ?? last?.region;
      if (!place?.codes?.length) throw new Error('请选择参保统筹地区');
      const p = {
        residentId: roster.value,
        event: stage.control.value,
        date: day.control.value,
        reference: ref.control.value,
        region: place,
        insuranceType: insurance.control.value,
        grade: grade.control.disabled ? '' : grade.control.value,
        service: service.control.disabled ? '' : service.control.value,
        startsOn: starts.control.disabled ? '' : starts.control.value,
        endsOn: ends.control.disabled ? '' : ends.control.value,
        note: note.control.value,
      };
      return ctx.command('ltci.record', p, {
        title: p.event,
        target: roster.selectedOptions[0].text,
        fields: [
          ['经办日期', p.date],
          ['参保统筹地区', region.label()],
          ['文书编号', p.reference],
          ['评估等级', p.grade],
          ['核定方式', p.service],
          ['待遇起始', p.startsOn],
          ['待遇截止', p.endsOn],
          ['文书补充', p.note],
        ].filter(([, v]) => v),
      });
    },
  });
}

export function longCare(ctx) {
  const people = ctx.state.residents || [];
  const current = currentResidents(ctx);
  const histories = new Map();
  for (const e of ctx.state.longCareEvents || []) {
    if (!histories.has(e.residentId)) histories.set(e.residentId, []);
    histories.get(e.residentId).push(e);
  }
  const rows = people
    .filter((p) => histories.has(p.id))
    .map((person) => ({ person, last: histories.get(person.id).at(-1) }));
  return page(
    ctx,
    '长期护理保险',
    '按长辈跟踪参保、申请、评估、待遇与复评记录。',
    current.length ? btn(ctx, '登记办理', () => registerLongCare(ctx, current), 'primary') : null,
    table(ctx, {
      title: '长护险经办台账',
      rows,
      search: {
        placeholder: '搜索长辈姓名、统筹地区或文书编号',
        value: (r) =>
          [
            r.person.name,
            ...histories.get(r.person.id).flatMap((e) => [e.regionLabel, e.reference]),
          ].join(' '),
      },
      filter: { label: '经办阶段', value: (r) => r.last.displayStatus },
      empty: '尚无长护险经办记录。可选择已有长辈档案，登记参保或补录已核定待遇。',
      cols: [
        { label: '长辈', view: (r) => named(residentAnchor(ctx, r.person), r.person.id) },
        { label: '统筹地区', view: (r) => r.last.regionLabel },
        { label: '最新阶段', view: (r) => badge(ctx, r.last.displayStatus) },
        { label: '最近办理', view: (r) => r.last.date },
        {
          label: '操作',
          view: (r) =>
            node('div', 'fx-actions', [
              btn(
                ctx,
                '查看凭证',
                () => history(ctx, r.person, histories.get(r.person.id)),
                'ghost',
              ),
              current.includes(r.person)
                ? btn(ctx, '继续办理', () => registerLongCare(ctx, current, r.person.id), 'ghost')
                : null,
            ]),
        },
      ],
    }),
  );
}
