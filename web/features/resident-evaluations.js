import { evaluationDetails, scaleForm } from './assessment-scale.js';
import { createRiskAssessment, riskDrawer } from './risk-reports.js';
import { staffLabel } from './people-labels.js';
import { badge, btn, canAct, choose, hasGrant, link, named, table } from './shared.js';

const sources = [
  { collection: 'followups', grant: 'clinical', show: riskDrawer },
  { collection: 'assessments', grant: 'care', show: evaluationDetails },
];

function visibleResident(ctx, id) {
  if (!['staff', 'owner'].includes(ctx.state.user.kind)) return;
  return ctx.state.residents.find(person => person.id === id && person.status !== '归档到期');
}

export function residentEvaluations(ctx, residentId) {
  const person = visibleResident(ctx, residentId);
  if (!person || !hasGrant(ctx, 'clinical', 'care')) return null;

  const rows = sources.filter(source => hasGrant(ctx, source.grant)).flatMap(source =>
    (ctx.state[source.collection] || []).filter(row => row.residentId === residentId)
      .map(row => ({ row, source, id: row.id })));
  rows.reverse().sort((a, b) => (b.row.date || '').localeCompare(a.row.date || ''));

  function open({ row, source }) {
    const live = ctx.current?.() || ctx;
    const record = (live.state[source.collection] || []).find(item =>
      item.id === row.id && item.residentId === residentId);
    if (!visibleResident(live, residentId) || !hasGrant(live, source.grant) || !record)
      return live.toast('这份报告已不在当前账号可查看的范围。');
    source.show(live, record);
  }

  const actions = choose();
  if (hasGrant(ctx,'clinical') && !rows.some(item => item.row.riskReport?.dimensions?.length)) {
    const preview = btn(ctx,'查看报告示例',async () => {
      preview.disabled = true;
      try {
        const response = await fetch('/api/care/risk-report-example', {cache:'no-store'});
        if (!response.ok) throw Error('当前无法打开报告示例。');
        const {resident,report} = await response.json();
        if (!preview.isConnected) return;
        const sample = {residents:[resident],residentRooms:{[resident.id]:'示例房间'},
          followups:[report],assessments:[],staffPositions:{names:{[report.openedBy]:'护士'}}};
        riskDrawer({...ctx,state:sample},report,{example:true});
      } catch (error) {
        if (preview.isConnected) ctx.toast(error.message);
      } finally {preview.disabled = false;}
    },'ghost');
    actions.append(preview);
  }
  function register(label, allowed, run) {
    if (person.status !== '在住' || !allowed(ctx)) return;
    actions.append(btn(ctx, label, () => {
      const live = ctx.current?.() || ctx;
      if (visibleResident(live, residentId)?.status !== '在住' || !allowed(live))
        return live.toast('当前无法为这位长辈登记评估。');
      run(live, residentId);
    }));
  }
  register('登记专项评估', c => hasGrant(c, 'clinical') && canAct(c, 'care.screen'), createRiskAssessment);
  register('登记能力评估', c => c.state.careScale && hasGrant(c, 'care') &&
    hasGrant(c, 'medical', 'clinical') && canAct(c, 'care.assess'), scaleForm);

  const panel = table(ctx, {title: '个人医疗评价', rows, action: actions.childElementCount ? actions : null,
    empty: '这位长辈暂无可查阅的评估报告。',
    cols: [
      { label: '评估项目', view: ({ row, source }) => source.collection === 'assessments'
        ? named('能力评估', row.scale?.version || row.source)
        : named(row.riskReport?.topic || row.subject || '专项筛查', row.riskReport?.instrument) },
      { label: '登记日期', view: ({ row }) => named(row.date || '未登记',
        row.scale?.assessedOn && row.scale.assessedOn !== row.date ? '评估于 ' + row.scale.assessedOn : '') },
      { label: '评估人员', view: ({ row }) => {
        if (row.scale?.assessors?.length) return row.scale.assessors.join('、');
        const recorder = row.recordedBy || row.openedBy;
        return recorder ? named(staffLabel(ctx, recorder), '登记人') : '未登记';
      }},
      { label: '评估等级', view: ({ row }) => {
        const level = row.riskReport?.level || row.scale?.gradeName || row.level;
        if (level) return badge(ctx, level, {'高风险':'red', '中风险':'amber', '低风险':'green'}[level]);
        return named('未核定', row.priority && '随访 · ' + row.priority);
      }},
      { label: '操作', align: 'end', view: item => link(ctx, '查看报告', () => open(item)) },
    ]});
  panel.classList.add('resident-evaluations');
  panel.setAttribute('aria-label', '个人医疗评价');
  return panel;
}
