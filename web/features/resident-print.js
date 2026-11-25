import { node } from './shared.js';

export async function printResidentSheet(ctx, title, content, styles, loadError) {
  const frame = node('iframe', 'roster-print-frame');
  frame.title = title + '打印预览';
  document.body.append(frame);
  const doc = frame.contentDocument;
  const sheet = frame.contentWindow;
  doc.documentElement.lang = 'zh-CN';
  doc.title = title;
  const style = doc.createElement('style');
  style.textContent = '@page{margin:12mm}body{margin:0;color:#182843;font:15px/1.45 sans-serif}' + styles;
  doc.head.append(style);
  doc.body.append(doc.importNode(content, true));
  sheet.addEventListener('afterprint', () => frame.remove(), { once: true });
  try {
    await Promise.all([...doc.images].map(image => image.decode()));
    sheet.focus();
    sheet.print();
  } catch {
    frame.remove();
    ctx.toast(loadError || '打印内容未能完整载入，请重试。');
  }
}
