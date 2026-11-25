import { materialForm, materialLabels } from './credential-form.js';
import { medicalResidentPicker } from './medical-resident-picker.js';
import { btn, node } from './shared.js';
import { workbookButton } from './assistant-workbook.js';

export const materialKinds = Object.fromEntries(Object.entries(materialLabels).map(([key, name]) => [name, key]));
export const registration = '长辈登记资料';
export const canDraftProfile = ctx => (ctx.available('dossier') || ctx.available('residents')) &&
  ctx.state.allowedActions?.includes('dossier.profile');

export function materialDestinations(row, getContext, active, accompany) {
  const ctx = getContext(), kind = materialKinds[row.category];
  const canFile = c => kind && c.available('billing') && c.state.allowedActions?.includes('ops.subsidyMaterial');
  const canRegister = c => kind && kind !== 'invoice' && c.state.allowedActions?.includes('dossier.credential') &&
    (c.available('dossier') || c.available('residents'));
  const canPrefill = c => canDraftProfile(c) && [registration,'身份证正面','户口本'].includes(row.category);
  if (!canFile(ctx) && !canRegister(ctx) && !canPrefill(ctx)) return node('small', '', '当前账号没有可填写此材料的权限。');
  const candidates = ctx.state.residents.filter(p => p.status !== '归档到期' && (canFile(ctx) || p.status !== '已退住'));
  const source = row.result?.profile || {fields: {}, ambiguous: []};
  const name = source.fields.name || row.result?.material?.fields?.name;
  const matches = name ? candidates.filter(person => person.name === name) : [];
  const uncertain = source.ambiguous?.some(key => key === 'name' || key === 'idNumber');
  const workspaceId = new URLSearchParams(location.hash.split('?')[1]).get('work') || '';
  const current = candidates.find(person => 'resident-' + person.id === workspaceId);
  const suggested = uncertain ? '' : matches.length === 1 ? matches[0].id : !name && current ? current.id : '';
  let selected;
  const draft = {kind, file: row.file, material: row.result?.material};
  const warning = node('p', 'assistant-document-hint');
  function currentPerson() {
    if (!active() || !selected || document.querySelector('dialog[open]')) return;
    return getContext().state.residents.find(p => p.id === selected.id && p.status !== '归档到期');
  }
  const registrationForm = btn(ctx, '预填长辈登记资料', async () => {
    const {openResidentProfileDraft} = await import('./profile-editor.js');
    const person = currentPerson(), live = getContext();
    if (!person || person.status === '已退住' || !canPrefill(live) || uncertain || name && name !== person.name) return;
    accompany();
    await openResidentProfileDraft(live, person, source);
  }, 'primary');
  const create = btn(ctx, '用这份资料新建档案', async () => {
    const {openNewResidentDraft} = await import('./profile-editor.js');
    const live = getContext();
    if (!active() || !canPrefill(live) || !live.state.allowedActions?.includes('care.register') || uncertain) return;
    accompany();
    await openNewResidentDraft(live, source);
  });
  const canCreate = canPrefill(ctx) && ctx.state.allowedActions?.includes('care.register') && !uncertain &&
    !ctx.state.residents.some(p=>name && p.name === name && p.status !== '归档到期');
  const profile = btn(ctx, '打开长辈证件档案', async () => {
    const {openDossier} = await import('./dossier.js');
    const live = getContext(), person = currentPerson();
    if (!person || person.status === '已退住' || !canRegister(live) || uncertain || name && name !== person.name) return;
    accompany();
    if (openDossier(live, person, null, 'registration'))
      materialForm(getContext(), person, draft);
  }, 'primary');
  const billing = btn(ctx, '打开补贴材料表单', async () => {
    const live = getContext(), person = currentPerson();
    if (!person || !canFile(live) || uncertain || name && name !== person.name) return;
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
    } finally { billing.disabled = !selected || uncertain || Boolean(name && name !== selected.name); }
  });
  function change(person) {
    selected = person;
    row.personId = person?.id || '';
    const mismatch = Boolean(person && name && name !== person.name);
    billing.disabled = !person || uncertain || mismatch;
    registrationForm.disabled = profile.disabled = billing.disabled || person?.status === '已退住';
    warning.textContent = uncertain ? '同一份材料含有冲突的身份信息，请分别上传清晰的单人资料。' : mismatch
      ? '证件姓名与所选档案不一致，请先核对原件和归属。'
      : matches.length > 1 ? '有同名长辈，请按床位核对归属。'
      : suggested ? '请核对推荐长辈的姓名和床位。' : '请确认这份原件属于哪位长辈。';
  }
  const initial = row.personId ?? suggested;
  change(null);
  const picker = medicalResidentPicker(ctx, candidates, initial, change, 20);
  return node('div', 'assistant-material-target', [picker, warning,
    canPrefill(ctx) && registrationForm, canCreate && create, canPrefill(ctx) && workbookButton(ctx, source.fields),
    canRegister(ctx) && profile, canFile(ctx) && billing]);
}
