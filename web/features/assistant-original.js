import { node } from './shared.js';

export function previewOriginal(ctx, row) {
  const content = node('div', 'assistant-original-view');
  const dialog = ctx.detail(row.file.name, content);
  const isPdf = row.mime === 'application/pdf';
  const picture = node('img');
  const status = node('p', 'fx-muted');
  status.setAttribute('role', 'status');
  const download = node('a', 'btn btn-ghost', '下载原件核对');
  const source = URL.createObjectURL(row.file);
  download.href = source;
  download.download = row.file.name;
  let page = 1, count = row.result?.pageCount || 1, request, rendered;
  const back = ctx.ui.button('上一页', () => show(page - 1), 'ghost');
  const next = ctx.ui.button('下一页', () => show(page + 1), 'ghost');
  content.append(picture, status, node('div', 'assistant-document-actions', [isPdf ? [back, next] : null, download]));
  async function show(number) {
    page = number;
    picture.alt = isPdf ? row.file.name + ' · 第 ' + page + ' 页' : row.file.name;
    if (!isPdf) {picture.src = source; return;}
    back.disabled = next.disabled = true;
    status.textContent = '正在读取第 ' + page + ' 页…';
    picture.hidden = true;
    request?.abort();
    const active = new AbortController();
    request = active;
    try {
      const response = await fetch('/api/assistant/documents/pages/' + page, {
        method: 'POST', headers: {'Content-Type':'application/pdf'}, body: row.file, signal: active.signal,
      });
      if (active.signal.aborted || !dialog.open) return;
      if ([401, 403].includes(response.status)) {
        dialog.close();
        await ctx.refreshWorkspace();
        return;
      }
      if (!response.ok) throw Error((await response.json()).error || '此页预览不可用。');
      const blob = await response.blob();
      if (active.signal.aborted || !dialog.open) return;
      count = Number(response.headers.get('X-Page-Count')) || count;
      if (rendered) URL.revokeObjectURL(rendered);
      rendered = URL.createObjectURL(blob);
      picture.src = rendered;
      picture.hidden = false;
      status.textContent = '第 ' + page + ' / ' + count + ' 页';
    } catch (error) {
      if (!active.signal.aborted && dialog.open) status.textContent = error.message;
    } finally {
      if (!active.signal.aborted && dialog.open) {
        back.disabled = page <= 1;
        next.disabled = page >= count;
      }
    }
  }
  dialog.addEventListener('close', () => {
    request?.abort();
    picture.removeAttribute('src');
    URL.revokeObjectURL(source);
    if (rendered) URL.revokeObjectURL(rendered);
  }, {once:true});
  show(1);
  return dialog;
}
