import { btn, node } from './shared.js';
import { residentLabel } from './people-labels.js';
import { reviewVisit } from './medical-visit-review.js';

const endpoint = '/api/assistant/visit-jobs';
const statuses = {queued:'排队中', running:'正在整理', ready:'待核对', failed:'需要处理'};

export function openVisitJobs(ctx, focusId = '') {
  const list = node('div', 'fx-profile');
  const note = node('p', 'fx-muted', '正在读取整理任务…');
  note.setAttribute('role', 'status');
  const body = node('div', 'fx-profile', [note, list]);
  const dialog = ctx.detail('我的就诊资料整理任务', body);
  let timer;
  const live = () => ctx.current?.() || ctx;
  async function review(row) {
    try {
      const data = await live().get(endpoint + '/' + row.draftId);
      const person = live().state.residents.find(r => r.id === data.residentId);
      if (!dialog.open) return;
      if (!person || !data.draft) throw Error('请刷新后核对档案状态。');
      const urls = data.draft.attachments.map(a => endpoint + '/' + row.draftId + '/originals/' + a.id);
      reviewVisit(live(), person, data.draft, urls, dialog);
    } catch (error) { note.textContent = error.message; }
  }
  async function retry(row) {
    try {
      const response = await fetch(endpoint + '/' + row.draftId + '/retry', {method:'POST'});
      if (!response.ok) throw Error((await response.json()).error || '无法重新整理');
      await refresh();
    } catch (error) { note.textContent = error.message; }
  }
  let sequence = 0;
  async function refresh() {
    const ticket = ++sequence;
    clearTimeout(timer);
    try {
      const {items} = await live().get(endpoint);
      if (!dialog.open || sequence !== ticket) return;
      list.replaceChildren();
      for (const row of items) {
        const person = live().state.residents.find(r => r.id === row.residentId);
        if (!person) continue;
        const action = row.state === 'ready' ? btn(ctx, '核对草稿', () => review(row), 'primary')
          : row.state === 'failed' ? btn(ctx, '重新整理', () => retry(row)) : null;
        const item = node('section', 'fx-panel', [
          node('h3', '', residentLabel(live(), person)), node('p', '', statuses[row.state]),
          row.error && node('p','form-error',row.error), node('small','fx-muted',row.taskId), action,
        ]);
        if (row.draftId === focusId) list.prepend(item);
        else list.append(item);
      }
      note.textContent = list.children.length ? '可关闭窗口继续对话，稍后从健康助理的「整理任务」回来核对。'
        : '当前没有等待核对的就诊资料。';
      if (items.some(row => ['queued','running'].includes(row.state)))
        timer = setTimeout(refresh, 3000);
    } catch (error) {
      if (dialog.open && sequence === ticket) { list.replaceChildren(); note.textContent = error.message; }
    }
  }
  body.append(btn(ctx, '刷新', refresh));
  dialog.addEventListener('close', () => { ++sequence; clearTimeout(timer); }, {once:true});
  refresh();
  return dialog;
}
