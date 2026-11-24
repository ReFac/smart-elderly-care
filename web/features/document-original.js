import { named, node } from './shared.js';

export function asBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('读取原件失败，请重新选择。'));
    reader.readAsDataURL(file);
  });
}

export function originalViewer(doc, onPage = () => {}) {
  const base = '/api/documents/' + encodeURIComponent(doc.id);
  const pdf = doc.mime === 'application/pdf';
  const count = doc.pageCount || 1;
  const download = node('a', 'btn btn-secondary', pdf ? '下载 PDF 原件' : '打开原尺寸照片');
  download.href = base + '/image';
  if (pdf) download.download = doc.filename || 'document.pdf';
  else { download.target = '_blank'; download.rel = 'noopener noreferrer'; }
  const picker = node('select');
  if (pdf) for (let i = 1; i <= count; i++) picker.add(new Option('第 ' + i + ' 页 / 共 ' + count + ' 页', String(i)));
  const image = node('img');
  const ns = 'http://www.w3.org/2000/svg';
  const canvas = document.createElementNS(ns, 'svg');
  canvas.setAttribute('width', '100%');
  canvas.setAttribute('aria-hidden', 'true');
  const marker = document.createElementNS(ns, 'rect');
  marker.setAttribute('fill', '#ffd567'); marker.setAttribute('fill-opacity', '.30');
  marker.setAttribute('stroke', '#946100'); marker.setAttribute('stroke-width', '3');
  canvas.append(marker);
  let page, box;
  function draw() {
    const w = image.naturalWidth, h = image.naturalHeight;
    if (!w || !h) return;
    canvas.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    if (!box) return;
    ['x','y','width','height'].forEach((name, i) =>
      marker.setAttribute(name, box[i] * (pdf ? (i % 2 ? h : w) / 1000 : 1)));
  }
  const error = node('small', 'form-error');
  function selectPage(next) {
    if (page === next || !Number.isInteger(next) || next < 1 || next > count) return;
    page = next;
    box = null;
    if (pdf) picker.value = String(next);
    error.textContent = '';
    marker.removeAttribute('width');
    const url = pdf ? base + '/pages/' + page : base + '/image';
    image.src = url;
    image.alt = '文书原件第 ' + page + ' 页';
    onPage(page);
  }
  image.addEventListener('load', draw);
  image.addEventListener('error', () => { error.textContent = '该页预览加载失败，请打开原件核对。'; });
  picker.addEventListener('change', () => selectPage(Number(picker.value)));
  const element = node('figure', 'fx-original', [
    pdf ? node('label', 'field', [node('span', '', '原件页码'), picker]) : null,
    node('div', 'document-page-preview', [image, canvas]), error, node('figcaption', '', [
      doc.filename ? named(doc.filename, Number.isFinite(doc.bytes) ? Math.ceil(doc.bytes / 1024) + ' KiB' : '') : null,
      download,
    ]),
  ]);
  selectPage(1);
  return { element, selectPage, get page() { return page; }, highlight(line) {
    if (line) selectPage(line.page || 1);
    box = line?.box;
    if (box) draw();
    else marker.removeAttribute('width');
  } };
}
