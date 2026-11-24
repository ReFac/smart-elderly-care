import { el, icon } from '../lib/ui.js';
import { node } from './shared.js';

export function replyReader(report) {
  const check = el('input');
  check.type = 'checkbox';
  const label = node('label', 'assistant-auto', [check, icon('speaker', 15), '朗读']);
  const player = el('audio', 'assistant-audio');
  player.controls = true;
  player.hidden = true;
  const queue = [];
  let session;

  function stop() {
    queue.length = 0;
    session?.abort();
    session = null;
    player.pause();
    player.removeAttribute('src');
    player.load();
    player.hidden = true;
  }
  check.addEventListener('change', () => { if (!check.checked) stop(); });

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
          player.hidden = false;
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
            player.play().catch(err => {
              if (active.signal.aborted) return;
              if (err.name === 'NotAllowedError') report('音频已就绪，点击播放即可朗读。');
              else fail();
            });
          });
        } finally {
          URL.revokeObjectURL(url);
        }
      }
    } catch (error) {
      if (!active.signal.aborted) { queue.length = 0; report(error.message); }
    } finally {
      if (session === active) { session = null; player.hidden = true; }
    }
  }

  return {
    label, player, stop,
    get enabled() { return check.checked; },
    enqueueSentence(sentence, context) {
      if (!check.checked) return;
      queue.push({ ...context, sentence });
      if (!session) void drain();
    },
    enqueue(item, context) {
      if (!check.checked || item?.role !== 'assistant' || !item.requestId) return;
      const count = Math.ceil(Array.from(item.content).length / 600);
      for (let part = 0; part < count; part++)
        queue.push({ ...context, part, requestId: item.requestId });
      if (!session) void drain();
    },
  };
}
