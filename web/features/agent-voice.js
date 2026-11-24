import { capture } from './audio-capture.js';
import { el, icon } from '../lib/ui.js';

// Hold with the pointer, Space or Enter. Ending a gesture releases the microphone exactly once.
export function holdToSpeak({ upload, onText, onState, available, record = capture }) {
  const control = el('button', 'assistant-hold');
  const label = el('span', '', '按住说话');
  control.type = 'button';
  control.append(icon('mic', 19), label);
  control.setAttribute('aria-label', '按住说话，松开转写');
  control.setAttribute('aria-keyshortcuts', 'Space Enter');
  let phase = 'idle',
    generation = 0,
    held = false,
    stop,
    pointerId,
    controller;
  const active = (turn) => turn === generation && control.isConnected;
  function setPhase(value, status = '') {
    phase = value;
    control.dataset.phase = phase;
    label.textContent = {
      idle: '按住说话',
      starting: '开启麦克风',
      recording: '松开转写',
      uploading: '正在转写…',
    }[value];
    control.setAttribute('aria-pressed', String(phase === 'recording'));
    onState(phase, status);
  }
  async function transcribe(blob, turn) {
    if (!active(turn)) return;
    stop = null;
    held = false;
    if (!blob) {
      setPhase('idle', '录音过短，请再按久一点。');
      return;
    }
    controller = new AbortController();
    setPhase('uploading');
    try {
      const result = await upload(blob, controller.signal);
      if (!active(turn)) return;
      controller = null;
      setPhase('idle');
      onText(result);
    } catch (error) {
      if (active(turn)) setPhase('idle', error.message || '转写失败，请重新录音。');
    }
  }
  async function begin() {
    if (phase !== 'idle' || control.disabled) return;
    const reason = available();
    if (reason) {
      onState('idle', reason);
      return;
    }
    const turn = ++generation;
    held = true;
    setPhase('starting', '请允许使用麦克风，按住说话。');
    try {
      const finish = await record(
        (blob) => transcribe(blob, turn),
        () => {},
        () => active(turn) && held,
      );
      if (!active(turn) || !held) {
        finish?.(false);
        return;
      }
      stop = finish;
      setPhase('recording', '正在听，松开即可转写。');
    } catch (error) {
      if (!active(turn)) return;
      held = false;
      setPhase(
        'idle',
        error.name === 'NotAllowedError'
          ? '请在浏览器中允许使用麦克风，或直接输入文字。'
          : error.message || '无法开启麦克风。',
      );
    }
  }
  function release() {
    pointerId = null;
    if (!held) return;
    held = false;
    if (phase === 'recording') stop?.();
    else if (phase === 'starting') {
      generation++;
      setPhase('idle', '请按住直到麦克风开启，再松开。');
    }
  }
  function cancel() {
    ++generation;
    held = false;
    pointerId = null;
    stop?.(false);
    stop = null;
    controller?.abort();
    controller = null;
    setPhase('idle');
  }
  control.addEventListener('pointerdown', (event) => {
    if (!event.isPrimary || event.button !== 0 || phase !== 'idle') return;
    event.preventDefault();
    control.focus({ preventScroll: true });
    pointerId = event.pointerId;
    try {
      control.setPointerCapture(pointerId);
    } catch {}
    begin();
  });
  control.addEventListener('pointerup', (event) => {
    if (event.pointerId === pointerId) release();
  });
  control.addEventListener('pointercancel', (event) => {
    if (event.pointerId === pointerId) cancel();
  });
  control.addEventListener('lostpointercapture', (event) => {
    if (held && event.pointerId === pointerId) cancel();
  });
  control.addEventListener('contextmenu', (event) => event.preventDefault());
  control.addEventListener('keydown', (event) => {
    if (![' ', 'Enter'].includes(event.key)) return;
    event.preventDefault();
    if (!event.repeat) begin();
  });
  control.addEventListener('keyup', (event) => {
    if (![' ', 'Enter'].includes(event.key)) return;
    event.preventDefault();
    release();
  });
  control.addEventListener('blur', () => {
    if (held) cancel();
  });
  return { control, cancel };
}

export function voiceServiceReason(service) {
  if (!service) return '当前账号未开放语音，可直接输入文字。';
  return (
    {
      inactive: '机构语音服务尚未开通，可先输入文字。',
      disabled: '机构已暂停语音转写，可先输入文字。',
      exhausted: '机构语音额度已用完，可先输入文字。',
      unconfigured: '语音服务待配置，可先输入文字。',
    }[service.state] || ''
  );
}
