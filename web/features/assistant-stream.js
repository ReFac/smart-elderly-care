export async function streamReply(path, payload, signal, event) {
  const response = await fetch(path, {
    method: 'POST', cache: 'no-store', signal,
    headers: { 'Content-Type': 'application/json', Accept: 'application/x-ndjson' },
    body: JSON.stringify(payload),
  });
  const interrupted = () => new Error('答复传输中断，请重试。');
  const fail = (message, status) => Object.assign(
    new Error(message || '暂时无法连接助理，请重试。'), { status },
  );
  if (!response.ok) throw fail((await response.json()).error, response.status);
  if (!response.headers.get('Content-Type')?.includes('application/x-ndjson')) return response.json();
  let result, remaining = '';
  function consume(piece, final = false) {
    const lines = (remaining + piece).split('\n');
    remaining = final ? '' : lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      const frame = JSON.parse(line);
      if (frame.type === 'done') result = frame.result;
      else if (frame.type === 'error') throw fail(frame.error, frame.status);
      else event(frame);
    }
  }
  if (!response.body?.getReader) consume(await response.text(), true);
  else {
    const reader = response.body.getReader();
    const text = new TextDecoder();
    try {
      while (!result) {
        const { value, done } = await reader.read();
        consume(text.decode(value, { stream: !done }), done);
        if (done) break;
      }
    } finally {
      await reader.cancel().catch(() => {});
    }
  }
  if (!result) throw interrupted();
  return result;
}
