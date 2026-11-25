import { canAct } from './shared.js';

// Only fixed business form openers receive the current workbench context. Speech
// text and model-generated values cannot become form defaults or command payloads.
const forms = new Map([
  ['staffAdd', ['access', 'access.create', async ctx => (await import('./access.js')).editAccount(ctx, 'staff')]],
  ['residentAdd', ['residents', 'care.register', async ctx => (await import('./admission.js')).register(ctx)]],
  ['admission', ['residents', 'care.admit', async ctx => (await import('./admission.js')).allocate(ctx)]],
  ['trial', ['residents', 'care.admit', async ctx => (await import('./admission.js')).allocate(ctx, null, null, 'trial')]],
  ['shiftAdd', ['shifts', 'ops.shift', async ctx => (await import('./operations.js')).shiftForm(ctx)]],
  ['inventoryAdd', ['inventory', 'ops.addItem', async ctx => (await import('./inventory-dedupe.js')).addItem(ctx)]],
  ['stockIn', ['inventory', 'ops.stock', async ctx => (await import('./operations.js')).stock(ctx, '入库')]],
  ['stockOut', ['inventory', 'ops.stock', async ctx => (await import('./operations.js')).stock(ctx, '出库')]],
  ['vitalAdd', ['care', 'care.vital', async ctx => (await import('./care.js')).vitalForm(ctx)]],
  ['medicationAdd', ['medications', 'care.addMedication', async ctx => (await import('./care.js')).medicationForm(ctx)]],
  ['medicationCheck', ['care', 'care.confirmMedRound', async ctx => (await import('./med-rounds.js')).openMedicationRound(ctx)]],
  ['billAdd', ['billing', 'ops.bill', async ctx => (await import('./billing.js')).generate(ctx)]],
  ['depositAdd', ['billing', 'ops.deposit', async ctx => (await import('./cashier.js')).recordCash(ctx)]],
  ['expenseAdd', ['billing', 'ops.expense', async ctx => (await import('./settlements.js')).expenseForm(ctx)]],
  ['leadAdd', ['leads', 'leads.register', async ctx => (await import('./leads.js')).registerLead(ctx)]],
  ['longCareAdd', ['longCare', 'ltci.record', async ctx => (await import('./long-care.js')).registerLongCare(ctx)]],
  ['scheduleAdd', ['care', 'care.saveSchedule', async ctx => (await import('./scheduled-work.js')).openScheduledPlan(ctx)]],
  ['reportAdd', ['reports', 'ops.report', async ctx => (await import('./operations.js')).reportForm(ctx)]],
  ['visitManual', ['dossier', 'dossier.confirmVisit', async ctx => (await import('./medical-visit-intake.js')).openVisitEditor(ctx, null, 'manual')]],
]);

export function manualFormAvailable(ctx, action) {
  const entry = forms.get(action.form);
  return Boolean(entry && entry[0] === action.route && ctx.available(entry[0]) && canAct(ctx, entry[1]));
}

export function openManualForm(ctx, action) {
  if (!manualFormAvailable(ctx, action)) return ctx.toast('当前账号没有此项操作权限');
  const [route, , open] = forms.get(action.form);
  return ctx.go(route, action.tab, async () => {
    const current = ctx.current?.() || ctx;
    if (!manualFormAvailable(current, action)) return current.toast('当前账号没有此项操作权限');
    try {
      await open(current);
    } catch (error) {
      current.toast(error.message || '暂时无法打开表单');
    }
  });
}
