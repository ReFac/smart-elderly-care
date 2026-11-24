import { btn, node } from './shared.js';

function pcmWave(samples, count, rate) {
  const bytes = new ArrayBuffer(44 + count * 2);
  const out = new DataView(bytes);
  const tag = (pos, value) =>
    [...value].forEach((letter, i) => out.setUint8(pos + i, letter.charCodeAt(0)));
  tag(0, 'RIFF');
  out.setUint32(4, 36 + count * 2, true);
  tag(8, 'WAVE');
  tag(12, 'fmt ');
  out.setUint32(16, 16, true);
  out.setUint16(20, 1, true);
  out.setUint16(22, 1, true);
  out.setUint32(24, rate, true);
  out.setUint32(28, rate * 2, true);
  out.setUint16(32, 2, true);
  out.setUint16(34, 16, true);
  tag(36, 'data');
  out.setUint32(40, count * 2, true);
  let pos = 44;
  for (const chunk of samples)
    for (const v of chunk) {
      if (pos === bytes.byteLength) break;
      out.setInt16(pos, Math.max(-32768, Math.min(32767, Math.round(v * 32768))), true);
      pos += 2;
    }
  return new Blob([bytes], { type: 'audio/wav' });
}

// Capture linear PCM at a supported sample rate. Chromium normally records WebM in MediaRecorder.
export async function capture(onReady, onStatus, stillOpen) {
  if (!navigator.mediaDevices?.getUserMedia)
    throw new Error('麦克风需要安全连接，可以选择已有录音。');
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1 },
    video: false
  });
  if (!stillOpen()) {
    stream.getTracks().forEach((t) => t.stop());
    return;
  }
  let ac,
    timer,
    finished = false;
  const close = () => {
    stream.getTracks().forEach((track) => track.stop());
    if (ac && ac.state !== 'closed') ac.close().catch(() => {});
    clearInterval(timer);
  };
  try {
    ac = new AudioContext({ sampleRate: 16000 });
    await ac.audioWorklet.addModule('/features/pcm-recorder.js');
    if (!stillOpen()) {
      close();
      return;
    }
    const source = ac.createMediaStreamSource(stream);
    const recorder = new AudioWorkletNode(ac, 'pcm-recorder');
    const silent = ac.createGain();
    silent.gain.value = 0;
    source.connect(recorder).connect(silent).connect(ac.destination);
    const chunks = [];
    let count = 0;
    function finish(deliver = true) {
      if (finished) return;
      finished = true;
      close();
      if (deliver) onReady(count ? pcmWave(chunks, count, ac.sampleRate) : null);
    }
    recorder.port.onmessage = (e) => {
      if (finished) return;
      chunks.push(e.data);
      count = Math.min(120 * ac.sampleRate, count + e.data.length);
      if (count === 120 * ac.sampleRate) finish();
    };
    await ac.resume();
    timer = setInterval(
      () => onStatus('正在录音 · ' + Math.floor(count / ac.sampleRate) + ' / 120 秒'),
      250
    );
    return finish;
  } catch (e) {
    close();
    throw e;
  }
}

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
  status.setAttribute('aria-live', 'polite');
  const err = node('div', 'form-error');
  err.setAttribute('role', 'alert');
  const consent = node('input');
  consent.type = 'checkbox';
  let audio = null,
    transcriptId = '',
    finish,
    selectionVersion = 0,
    busy = false;
  const label = (name, el) => node('label', 'field', [node('span', '', name), el]);
  function selected(blob) {
    selectionVersion += 1;
    audio = blob;
    transcriptId = '';
    transcript.readOnly = false;
    transcript.value = '';
    note.value = '';
    status.textContent = blob ? '已选录音 · ' + Math.ceil(blob.size / 1024) + ' KiB' : '';
    consent.checked = false;
    record.textContent = '开始录音';
    finish = null;
  }
  const record = btn(ctx, '开始录音', async () => {
    if (finish) {
      finish();
      return;
    }
    err.textContent = '';
    record.disabled = true;
    try {
      file.value = '';
      selected(null);
      const version = selectionVersion;
      const active = () => dialog.open && version === selectionVersion;
      const stop = await capture(selected, (text) => (status.textContent = text), active);
      if (!active()) {
        stop?.(false);
        return;
      }
      finish = stop;
      if (finish) record.textContent = '结束录音';
    } catch (e) {
      err.textContent = e.message || '无法使用麦克风';
    } finally {
      record.disabled = false;
    }
  });
  const send = btn(ctx, '用 DeepSeek 转写', async () => {
    err.textContent = '';
    if (!task.value || !audio || finish || !consent.checked) {
      err.textContent = '请选择工单和已录好的音频，并确认发送。';
      return;
    }
    busy = true;
    send.disabled = task.disabled = file.disabled = record.disabled = submit.disabled = true;
    try {
      if (
        !(await ctx.confirmChange({
          title: '发送录音到 DeepSeek',
          target: task.selectedOptions[0]?.textContent,
          fields: [['处理方式', '本段音频将使用机构 ASR 额度转写。']],
          confirmLabel: '确认发送',
        }))
      )
        return;
      const reply = await fetch('/api/media/asr/' + encodeURIComponent(task.value), {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream', 'X-DeepSeek-Consent': 'yes' },
        body: audio
      });
      const result = await reply.json();
      await ctx.refreshWorkspace();
      if (!reply.ok) throw new Error(result.error || '识别失败');
      if (!dialog.open) return;
      transcript.value = result.text;
      transcript.readOnly = true;
      transcriptId = result.transcriptId;
      note.value = result.text.slice(0, 1000);
      status.textContent =
        '转写完成 · ' + Math.ceil(result.durationMs / 1000) + ' 秒。请核对并编辑拟写入内容。';
    } catch (e) {
      err.textContent = e.message;
    } finally {
      busy = false;
      send.disabled = task.disabled = file.disabled = record.disabled = submit.disabled = false;
    }
  });
  file.addEventListener('change', () => {
    finish?.(false);
    const blob = file.files[0];
    err.textContent = '';
    if (blob?.size > 8 * 1024 * 1024) {
      file.value = '';
      selected(null);
      err.textContent = '录音上限为 8 MiB';
      return;
    }
    selected(blob);
  });
  task.addEventListener('change', () => {
    finish?.(false);
    selected(null);
    file.value = '';
  });
  const submit = node('button', 'btn btn-primary', '提交人工确认');
  submit.type = 'submit';
  form.append(
    label('拟完成的工单', task),
    node('div', 'fx-actions', [record, label('选择录音（WAV / Ogg Opus）', file)]),
    node('label', 'access-check', [consent, '同意将这段录音发送至 DeepSeek，并使用机构语音额度。']),
    send,
    status,
    label('转写原文或手工输入', transcript),
    label('拟写入的执行记录', note),
    err,
    submit
  );
  form.onsubmit = async (e) => {
    e.preventDefault();
    if (busy || submit.disabled) return;
    submit.disabled = true;
    try {
      if (
        await ctx.command('gw.propose', {
          taskId: task.value,
          transcript: transcript.value,
          note: note.value,
          requestId,
          targetAction: 'care.completeTask',
          ...(transcriptId ? { transcriptId } : {})
        })
      )
        dialog.close();
    } finally {
      submit.disabled = false;
    }
  };
  const dialog = ctx.detail('登记语音变更草稿', form);
  dialog.addEventListener('close', () => finish?.(false), { once: true });
}
