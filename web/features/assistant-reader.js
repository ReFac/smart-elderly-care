import { el, icon } from '../lib/ui.js';
import { node } from './shared.js';

export function replyReader(report, exit) {
  const check = el('input');
  check.type = 'checkbox';
  check.disabled = true;
  const label = node('label', 'assistant-read-option', [check, icon('speaker', 15), '朗读']);
  label.title = '仅朗读按住说话的语音答复';
  check.setAttribute('aria-description', label.title);

  const player = el('audio', 'assistant-audio');
  player.hidden = true;
  const wave = el('span', 'assistant-reader-wave');
  wave.setAttribute('aria-hidden', 'true');
  for (const level of [8, 15, 22, 14, 25, 16, 7]) {
    const bar = el('span');
    bar.style.setProperty('--wave-height', level + 'px');
    wave.append(bar);
  }
  const status = el('strong', 'assistant-reader-status');
  status.setAttribute('role', 'status');
  const toggle = el('button', 'assistant-reader-toggle', '暂停');
  const close = el('button', 'assistant-reader-close', '退出');
  toggle.type = close.type = 'button';
  const popup = node('div', 'assistant-reader', [
    node('div', 'assistant-reader-caption', [wave, status]),
    node('div', 'assistant-reader-controls', [toggle, close]), player,
  ]);
  popup.hidden = true;
  popup.setAttribute('role', 'group');
  popup.setAttribute('aria-label', '答复朗读');

  const queue = [];
  let session, play, paused = false;

  function playback(state) {
    popup.dataset.playback = state;
    status.textContent = {
      playing: '正在朗读',
      paused: '朗读已暂停',
      ready: '朗读已就绪',
      loading: '正在准备朗读',
    }[state];
    toggle.textContent = ['paused', 'ready'].includes(state) ? '继续' : '暂停';
  }
  player.addEventListener('playing', () => {
    if (!popup.hidden && !paused) playback('playing');
  });
  toggle.addEventListener('click', () => {
    if (paused || popup.dataset.playback === 'ready') {
      paused = false;
      playback('loading');
      play?.();
    } else {
      paused = true;
      player.pause();
      playback('paused');
    }
  });
  close.addEventListener('click', () => {
    stop();
    exit();
  });

  function stop() {
    queue.length = 0;
    session?.abort();
    session = null;
    resetPlayer();
  }
  function resetPlayer() {
    popup.hidden = true;
    play = null;
    paused = false;
    player.pause();
    if (player.hasAttribute('src')) {
      player.removeAttribute('src');
      player.load();
    }
  }

  async function prepare(body, signal) {
    try {
      const response = await fetch('/api/assistant/chat/speech', {
        method: 'POST', signal, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error((await response.json()).error || '朗读暂时不可用');
      return { blob: await response.blob() };
    } catch (error) {
      return { error };
    }
  }

  async function drain() {
    const active = new AbortController();
    session = active;
    let next;
    try {
      while ((next || queue.length) && !active.signal.aborted) {
        const clip = await (next || prepare(queue.shift(), active.signal));
        if (clip.error) throw clip.error;
        if (active.signal.aborted) break;
        next = queue.length ? prepare(queue.shift(), active.signal) : null;
        const url = URL.createObjectURL(clip.blob);
        try {
          if (active.signal.aborted) break;
          player.src = url;
          playback(paused ? 'paused' : 'loading');
          popup.hidden = false;
          await new Promise((resolve, reject) => {
            const done = () => { cleanup(); resolve(); };
            const fail = () => { cleanup(); reject(new Error('音频无法播放')); };
            const cleanup = () => {
              player.removeEventListener('ended', done);
              player.removeEventListener('error', fail);
              active.signal.removeEventListener('abort', done);
            };
            player.addEventListener('ended', done);
            player.addEventListener('error', fail);
            active.signal.addEventListener('abort', done);
            play = () => player.play().catch(err => {
              if (active.signal.aborted || err.name === 'AbortError') return;
              if (err.name === 'NotAllowedError') playback('ready');
              else fail();
            });
            if (!paused) play();
          });
        } finally {
          if (session === active) {
            play = null;
            if (!paused) playback('loading');
          }
          URL.revokeObjectURL(url);
        }
      }
    } catch (error) {
      if (!active.signal.aborted) { queue.length = 0; report(error.message); }
    } finally {
      if (session === active) {
        session = null;
        resetPlayer();
      }
    }
  }

  return {
    label, popup, stop,
    get voicePreference() { return check.checked; },
    enableForVoice(available) {
      check.disabled = !available;
    },
    enqueueSentence(sentence, context) {
      queue.push({ ...context, sentence });
      if (!session) void drain();
    },
    enqueue(item, context) {
      if (item?.role !== 'assistant' || !item.requestId) return;
      const count = Math.ceil(Array.from(item.content).length / 600);
      for (let part = 0; part < count; part++)
        queue.push({ ...context, part, requestId: item.requestId });
      if (!session) void drain();
    },
  };
}
