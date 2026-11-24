import { node } from './shared.js';
import { holdToSpeak } from './agent-voice.js';

export function voiceProposal(ctx, tasks, requestId) {
  const form = node('form', 'fx-profile');
  const task = node('select');
  task.required = true;
  for (const [id, title] of tasks) task.add(new Option(title, id));
  const transcript = node('textarea');
  transcript.required = true;
  transcript.maxLength = 1000;
  transcript.rows = 3;
  const note = node('textarea');
  note.required = true;
  note.maxLength = 1000;
  note.rows = 3;
  const file = node('input');
  file.type = 'file';
  file.accept = '.wav,.ogg,.opus,audio/wav,audio/ogg';
  const status = node('p', 'fx-muted');
  status.setAttribute('role', 'status');
  const error = node('div', 'form-error');
  error.setAttribute('role', 'alert');
  const submit = node('button', 'btn btn-primary', '提交人工确认');
  submit.type = 'submit';
  let dialog, transcriptId = '', submitting = false, picking = false, phase = 'idle';
  let fileRequest;
  const label = (name, input) => node('label', 'field', [node('span', '', name), input]);
  function sync() {
    const busy = phase !== 'idle' || picking || submitting;
    file.disabled = task.disabled = busy;
    voice.control.disabled = !task.value || picking || submitting;
    submit.disabled = busy || !task.value;
  }
  function setTranscript(result) {
    transcript.value = result.text;
    transcript.readOnly = true;
    transcriptId = result.transcriptId;
    note.value = result.text.slice(0, note.maxLength);
    status.textContent = '已转写，请核对拟写入的执行记录。';
    error.textContent = '';
  }
  async function upload(blob, signal) {
    error.textContent = '';
    const reply = await fetch('/api/media/asr/' + encodeURIComponent(task.value), {
      method: 'POST', signal,
      headers: { 'Content-Type': 'application/octet-stream', 'X-DeepSeek-Consent': 'yes' }, body: blob,
    });
    const result = await reply.json();
    if (reply.status === 401 || reply.ok) await ctx.refreshWorkspace();
    if (!reply.ok) throw new Error(result.error || '语音转写失败。');
    return result;
  }
  const voice = holdToSpeak({
    available: () => task.value ? '' : '请先选择工单。',
    onState(value, message) {
      phase = value;
      status.textContent = message || (value === 'uploading' ? '正在转写…' : '');
      sync();
    },
    upload,
    onText(result) { if (dialog.open) setTranscript(result); },
  });
  file.addEventListener('change', async () => {
    const blob = file.files[0];
    file.value = '';
    if (!blob || !task.value) return;
    if (blob.size > 8 * 1024 * 1024) { error.textContent = '录音文件上限为 8 MiB。'; return; }
    picking = true;
    sync();
    status.textContent = '正在转写录音文件…';
    fileRequest = new AbortController();
    try {
      const result = await upload(blob, fileRequest.signal);
      if (dialog.open) setTranscript(result);
    } catch (e) {
      if (dialog.open) { error.textContent = e.message; status.textContent = ''; }
    } finally { picking = false; sync(); }
  });
  task.addEventListener('change', () => {
    transcriptId = '';
    transcript.readOnly = false;
    transcript.value = note.value = status.textContent = error.textContent = '';
    sync();
  });
  form.append(label('拟完成的工单', task),
    node('div', 'fx-actions', [voice.control, label('或选择录音文件转写', file)]), status,
    label('转写原文或手工输入', transcript), label('拟写入的执行记录', note), error, submit);
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (submit.disabled) return;
    submitting = true;
    sync();
    try {
      if (await ctx.command('gw.propose', { taskId: task.value, transcript: transcript.value,
        note: note.value, requestId, targetAction: 'care.completeTask',
        ...(transcriptId ? { transcriptId } : {}) })) dialog.close();
    } finally { submitting = false; sync(); }
  });
  sync();
  dialog = ctx.detail('登记语音变更草稿', form);
  dialog.addEventListener('close', () => { voice.cancel(); fileRequest?.abort(); }, { once:true });
}
