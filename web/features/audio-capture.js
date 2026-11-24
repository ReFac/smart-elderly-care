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
    throw new Error('麦克风需要 HTTPS 或本机地址，可直接输入文字。');
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1 },
    video: false,
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
    await ac.audioWorklet.addModule(new URL('./pcm-recorder.js', import.meta.url));
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
      250,
    );
    return finish;
  } catch (e) {
    close();
    throw e;
  }
}
