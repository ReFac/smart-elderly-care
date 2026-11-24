import { btn, choose, field, memo, node, today } from './shared.js';
import { residentLabel, staffLabel } from './people-labels.js';

const titles = { intro: '填写健康简介', addition: '补充健康情况', conversation: '记录本人健康谈话' };
const hints = {
  intro: '用一两句话说明已知的疾病或身体情况，保留病史或自述的来历。',
  addition: '写下新了解的健康情况。这段补充会随健康简介一同保留。',
  conversation: '只记录与这位长者本人交谈时说起的健康情况，并注明哪些是长者自述。',
};

function entry(ctx, row) {
  return node('article', 'fx-time-row', [
    node('time', '', row.day),
    node('div', 'fx-named', [
      node('p', '', row.text),
      row.staff ? node('small', 'fx-muted', staffLabel(ctx, { id: row.staffId, displayName: row.staff, role: row.role })) : null,
    ]),
  ]);
}

function citation(point) {
  return node('details', 'rounds-evidence', [
    node('summary', '', '核对出处 · ' + point.label),
    node('blockquote', '', point.quote),
    node('small', 'fx-muted', '档案记录 ' + point.recordId),
  ]);
}

export function healthProfile(ctx, person) {
  const panel = node('section', 'rounds-card');
  panel.dataset.roundsResidentId = person.id;
  const endpoint = '/api/residents/' + encodeURIComponent(person.id) + '/health-profile';
  const name = residentLabel(ctx, person);
  let data;
  async function load() {
    try {
      data = await ctx.get(endpoint);
      draw();
    } catch (error) {
      panel.replaceChildren(node('p', 'fx-muted', error.message), btn(ctx, '重新读取健康简介', load));
    }
  }
  async function save(action, payload, revision, review) {
    const choice = review ? await ctx.confirmChange({ ...review, target: name, allowComment: true }) : {};
    if (!choice) return false;
    const response = await fetch('/api/commands', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, revision, comment: choice.comment || '',
        payload: { ...payload, residentId: person.id, confirmed: true } }),
    });
    const result = await response.json();
    if (response.status === 409) {
      await load();
      throw new Error('档案刚有更新，请关闭此编辑窗，核对当前健康简介后重新填写。');
    }
    if (!response.ok) throw new Error(result.error || '健康记录保存失败');
    await load();
    ctx.toast('已保存到' + name + '的健康简介。');
    return true;
  }
  function edit(kind) {
    const revision = data.revision;
    const requestId = crypto.randomUUID();
    const dialog = ctx.dialog({
      title: titles[kind] + ' · ' + name,
      description: hints[kind],
      fields: [
        field('day', kind === 'conversation' ? '交谈日期' : '记录日期',
          { type: 'date', value: today(ctx), max: today(ctx) }),
        memo('text', kind === 'conversation' ? '长者自述与谈话记录' : '健康情况', true, {
          maxLength: 1600, value: kind === 'intro' ? data.intro?.text || '' : '',
        }),
      ],
      submitLabel: '核对并保存',
      onSubmit: values => save('care.healthNote', { ...values, kind, requestId }, revision, {
        title: titles[kind], fields: [['日期', values.day], ['保存内容', values.text]],
      }),
    });
    dialog.dataset.roundsResidentId = person.id;
  }
  async function generate(button) {
    const choice = await ctx.confirmChange({
      title: '整理本人的健康简介', target: name, confirmLabel: '生成草稿',
      fields: [['读取范围', '此人的登记介绍、本人健康谈话、已核对的就诊记录和病史'],
        ['提交至 DeepSeek', '发送该档案的健康摘录，用于撰写最多三条健康要点。']],
    });
    if (!choice || !panel.isConnected) return;
    button.disabled = true;
    button.textContent = '正在整理…';
    try {
      const response = await fetch(endpoint + '/draft', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ consent: true }) });
      const draft = await response.json();
      if (!response.ok) throw new Error(draft.error || '健康简介生成失败');
      if (!panel.isConnected) return;
      if (!draft.points.length) {
        ctx.toast('当前个人资料中没有足够的健康信息，可先记录健康谈话或手工填写。');
        return;
      }
      await load();
      const revision = data.revision;
      const form = node('form', 'fx-profile');
      const checks = draft.points.map(point => {
        const box = node('input');
        box.type = 'checkbox';
        box.checked = true;
        form.append(node('section', 'fx-profile', [
          node('label', 'access-check', [box, point.text]), citation(point),
        ]));
        return box;
      });
      const error = node('p', 'form-error');
      error.setAttribute('role', 'alert');
      const sign = node('button', 'btn btn-primary', '确认写入健康简介');
      sign.type = 'submit';
      form.prepend(node('p', 'fx-muted', '请逐条核对出处，取消勾选不合适的说法。AI 可能出错，已有人工补充会继续保留。'));
      form.append(error, sign);
      const dialog = ctx.detail('核对健康简介 · ' + name, form);
      dialog.dataset.roundsResidentId = person.id;
      form.onsubmit = async event => {
        event.preventDefault();
        const selected = checks.flatMap((checkbox, index) => checkbox.checked ? [index] : []);
        if (!selected.length) {error.textContent = '请至少勾选一条已核对的健康要点。'; return;}
        sign.disabled = true;
        try {
          if (await save('dossier.signHealthIntro', { draftId: draft.draftId, selected }, revision)) dialog.close();
        } catch (ex) { error.textContent = ex.message; }
        finally { sign.disabled = false; }
      };
    } catch (error) {
      ctx.toast(error.message);
    } finally {
      button.disabled = false;
      button.textContent = 'AI 整理健康简介';
    }
  }
  function draw() {
    const head = node('header', 'rounds-heading', [node('h3', '', '健康简介')]);
    const children = [head];
    if (data.intro) {
      const intro = data.intro;
      for (const text of intro.text.split('\n')) children.push(node('p', '', text));
      const author = intro.staff ? staffLabel(ctx, { id: intro.staffId, displayName: intro.staff, role: intro.role }) : '护理人员';
      children.push(node('small', 'fx-muted', (intro.kind === 'ai' ? 'AI 整理，由' : '由') +
        author + (intro.kind === 'ai' ? '核对' : '填写') + ' · ' + intro.day));
      if (intro.sources?.length) children.push(node('details', '', [
        node('summary', '', '查看简介依据（' + intro.sources.length + '）'), ...intro.sources.map(citation),
      ]));
    } else {
      children.push(node('p', 'fx-muted', '尚未填写健康简介。'));
    }
    if (data.additions.length) children.push(node('h4', '', '护理人员补充'), ...data.additions.map(r => entry(ctx, r)));
    if (data.conversations.length) children.push(node('details', '', [
      node('summary', '', '本人健康谈话（' + data.conversations.length + '）'),
      ...data.conversations.map(r => entry(ctx, r)),
    ]));
    const actions = choose();
    if (data.canGenerate) {
      const button = btn(ctx, 'AI 整理健康简介', () => generate(button), 'primary');
      actions.append(button);
    }
    if (data.canWrite) {
      actions.append(btn(ctx, '填写健康简介', () => edit('intro')), btn(ctx, '补充健康情况', () => edit('addition')),
        btn(ctx, '记录本人健康谈话', () => edit('conversation')));
    }
    if (actions.childElementCount) children.push(actions);
    panel.replaceChildren(...children);
  }
  panel.append(node('h3', '', '健康简介'));
  load();
  return panel;
}
