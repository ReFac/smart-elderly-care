import { materialForm, materialLabels } from './credential-form.js';
import { medicalResidentPicker } from './medical-resident-picker.js';
import { btn, node } from './shared.js';

export const materialKinds = Object.fromEntries(Object.entries(materialLabels).map(([key, name]) => [name, key]));

export function materialDestinations(row, getContext, active, accompany) {
  const ctx = getContext(), kind = materialKinds[row.category];
  const canFile = c => c.available('billing') && c.state.allowedActions?.includes('ops.subsidyMaterial');
  const canRegister = c => kind !== 'invoice' && c.state.allowedActions?.includes('dossier.credential') &&
    (c.available('dossier') || c.available('residents'));
  if (!canFile(ctx) && !canRegister(ctx)) return node('small', '', '当前账号没有可填写此材料的权限。');
  const candidates = ctx.state.residents.filter(p => p.status !== '归档到期' && (canFile(ctx) || p.status !== '已退住'));
  const name = row.result?.material?.fields?.name;
  const matches = name ? candidates.filter(person => person.name === name) : [];
  const suggested = matches.length === 1 ? matches[0].id : '';
  let selected;
  const draft = {kind, file: row.file, material: row.result?.material};
  const warning = node('p', 'assistant-document-hint');
  function currentPerson() {
    if (!active() || !selected || document.querySelector('dialog[open]')) return;
    return getContext().state.residents.find(p => p.id === selected.id && p.status !== '归档到期');
  }
  const profile = btn(ctx, '打开长辈证件档案', async () => {
    const {openDossier} = await import('./dossier.js');
    const live = getContext(), person = currentPerson();
    if (!person || person.status === '已退住' || !canRegister(live)) return;
    accompany();
    if (openDossier(live, person, null, 'registration'))
      materialForm(getContext(), person, draft);
  }, 'primary');
  const billing = btn(ctx, '打开补贴材料表单', async () => {
    const live = getContext(), person = currentPerson();
    if (!person || !canFile(live)) return;
    billing.disabled = true;
    try {
      const data = await live.get('/api/finance/subsidies?month=' + live.state.today.slice(0, 7));
      const current = currentPerson();
      if (!current || current.id !== person.id || !canFile(getContext())) return;
      const eligible = data.rows.find(r => r.residentId === current.id);
      if (!eligible || eligible.claim || (kind === 'invoice' && !eligible.invoiceMonths.length)) {
        warning.textContent = '该长辈本期没有可维护的此类补贴材料。';
        return;
      }
      accompany();
      getContext().go('billing', 'subsidies', () => materialForm(getContext(), current, {
        ...draft, filing: {month: data.month, revision: data.revision, invoiceMonths: eligible.invoiceMonths},
      }));
    } catch (err) {
      if (active()) warning.textContent = err.message || '读取补贴资格失败，请重试。';
    } finally { billing.disabled = !selected; }
  });
  function change(person) {
    selected = person;
    row.personId = person?.id || '';
    profile.disabled = !person || person.status === '已退住';
    billing.disabled = !person;
    warning.textContent = person && name && name !== person.name
      ? '证件姓名与所选档案不一致，请先核对原件和归属。'
      : matches.length > 1 ? '有同名长辈，请按床位核对归属。'
      : suggested ? '在可见档案中找到同名长辈，请核对姓名和床位。' : '请确认这份原件属于哪位长辈。';
  }
  const initial = row.personId ?? suggested;
  change(null);
  const picker = medicalResidentPicker(ctx, candidates, initial, change, 20);
  return node('div', 'assistant-material-target', [picker, warning,
    canRegister(ctx) && profile, canFile(ctx) && billing]);
}
