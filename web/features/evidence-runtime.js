import { node } from './shared.js';

export const runtimeNames = {deerflow: 'DeerFlow', direct: '平台直连（历史）', platform: '院务系统', pi: 'Pi（历史）'};

export function taskReceipt(runtime, taskId, title = '整理回执') {
  if (!runtime && !taskId) return null;
  const name = runtimeNames[runtime];
  return node('details', 'assistant-task-receipt', [
    node('summary', '', [node('span', '', title), name && [' · ', node('span', '', name)]]),
    node('dl', 'round-specialist-facts', [
      node('div', '', [node('dt', '', '本次执行组件'), node('dd', '', name || '暂无组件回执')]),
      taskId && node('div', '', [node('dt', '', '任务编号'), node('dd', '', taskId)]),
    ]),
  ]);
}
