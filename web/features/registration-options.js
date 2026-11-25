import { node, today } from './shared.js';
import { residentAnchor } from './people-labels.js';
import { group, textControl } from './profile-controls.js';

function selector(title, options, preferred) {
  const control = node('select');
  for (const [key, label] of options) control.add(new Option(label, key));
  if (preferred && options.some(([key]) => key === preferred)) control.value = preferred;
  return {control, element: node('label', 'field', [node('span', '', title), control])};
}

export function registrationOptions(ctx, name, inquiry) {
  const day = today(ctx);
  const earliest = new Date(day + 'T00:00:00Z');
  earliest.setUTCDate(earliest.getUTCDate() - 364);
  const kind = selector('档案类别', [['new','待入住'], ['archive','归档老人 · 仅保管资料']]);
  const campuses = ctx.state.campusOptions || [];
  const campus = campuses.length && selector('建档分院', campuses.map(c => [c.id, c.name]), inquiry?.campusId);
  const archive = textControl('原退住或归档日期', day, 'date', {
    min: earliest.toISOString().slice(0, 10), max: day, required:true,
  });
  const notice = node('div', 'admission-match');
  notice.setAttribute('aria-live','polite');
  const matches = () => ctx.state.residents.filter(r => r.name === name.value.trim() && r.status !== '归档到期');
  const update = () => {
    archive.element.hidden = archive.control.disabled = kind.control.value !== 'archive';
    const same = matches();
    notice.replaceChildren();
    if (same.length) notice.append(node('strong','','发现同名档案，请核对身份。'),
      ...same.map(r => node('div','',[residentAnchor(ctx,r), ' · ', r.id, ' · ', r.status])));
  };
  name.addEventListener('input', update);
  kind.control.addEventListener('change', update);
  update();
  return {
    element: group('建档信息', [kind.element, campus?.element, archive.element, notice]),
    values() {
      const same = matches(), archived = kind.control.value === 'archive';
      return {payload:{kind:kind.control.value, ...(campus && {campusId:campus.control.value}),
        ...(inquiry && {inquiryId:inquiry.id}), ...(archived && {archiveDate:archive.control.value}),
        ...(same.some(r=>r.status === '已退住') && {acknowledgeArchive:true})},
        details:[['档案类别', archived ? (ctx.state.retainServiceRecords ? '归档，档案保全' : '归档，日常资料保管 365 天') : '待入住'],
          ...(archived ? [['归档日期',archive.control.value]] : []),
          ...(same.length ? [['同名档案，请确认是不同的人',same.map(r=>r.name+' · '+r.id).join('、')]] : [])]};
    },
  };
}
