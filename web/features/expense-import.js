import { badge, btn, money, named, node, table, today } from './shared.js';
import { clearFileSelection, fileControl } from '../lib/file-control.js';

const sources = { bank: '银行对账单', electricity: '国网河南电费凭证' };
const states = { ready: '可入账', duplicate: '重复', review: '待核对', excluded: '非支出或无效交易' };
const field = (label, input) => node('label', 'field', [node('span', '', label), input]);

function downloadTemplate(source, day) {
  const rows = source === 'bank' ? [
    ['交易日期', '银行流水号', '收支方向', '交易金额', '对方户名', '摘要', '交易状态', '发票号码', '支出分类'],
    [day, 'EXAMPLE-BANK-001', '支出', '120.00', '示例收款单位', '演示电费', '成功', 'EXAMPLE-INV-001', '设施'],
    [day, 'EXAMPLE-BANK-002', '收入', '20.00', '示例退款单位', '演示收入', '成功', '', '其他'],
  ] : [
    ['缴费日期', '发票号码', '银行流水号', '实付金额', '收款单位', '缴费状态', '摘要'],
    [day, 'EXAMPLE-INV-001', 'EXAMPLE-BANK-001', '120.00', '示例收款单位', '已缴费', '演示电费'],
  ];
  const url = URL.createObjectURL(new Blob(['\uFEFF' + rows.map((row) => row.join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }));
  const a = node('a');
  a.download = sources[source] + '通用样例.csv';
  a.href = url;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('文件读取失败，请重新选择。'));
    reader.readAsDataURL(file);
  });
}

export function importExpenses(ctx) {
  const src = node('select');
  for (const [id, title] of Object.entries(sources)) src.add(new Option(title, id));
  const file = node('input');
  file.type = 'file';
  const helper = node('p', 'fx-muted');
  const load = btn(ctx, '预览文件', preview);
  const status = node('p', 'form-error');
  status.setAttribute('role', 'status');
  const results = node('div', 'fx-profile');
  const dialog = ctx.detail('导入机构支出', node('div', 'fx-profile', [
    node('div', 'access-field-pair', [field('凭证来源', src), field('已导出的文件', fileControl(file))]),
    helper,
    node('div', 'fx-actions', [btn(ctx, '下载通用 CSV 样例', () => downloadTemplate(src.value, today(ctx))), load]),
    status, results,
  ]));
  let sequence = 0;
  function reset() {
    sequence++;
    load.disabled = !file.files.length;
    results.replaceChildren();
    status.textContent = '';
  }
  function setSource() {
    file.accept = src.value === 'bank' ? '.csv' : '.csv,.xml';
    clearFileSelection(file);
    helper.textContent = src.value === 'bank'
      ? '支持 UTF-8 或 GB18030 编码的银行 CSV（最大 1 MiB）。预览将区分支出和贷方收入。'
      : '可导入电费缴费 CSV 或数字发票 XML（最大 1 MiB）。只有开票信息的凭证需核对实付记录。';
    reset();
  }
  async function preview() {
    const upload = file.files[0];
    if (!upload) return;
    if (upload.size > 1024 * 1024 || upload.size === 0) {
      status.textContent = '请选择 1 MiB 以内的非空文件。';
      return;
    }
    const active = ++sequence;
    const source = src.value;
    results.replaceChildren();
    load.disabled = true;
    status.textContent = '正在核对凭证…';
    try {
      const contentBase64 = await readFile(upload);
      if (active !== sequence) return;
      const response = await fetch('/api/finance/expense-import/preview', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ source, fileName: upload.name, contentBase64 }),
      });
      const data = await response.json();
      if (active !== sequence || !dialog.open) return;
      if (!response.ok) throw new Error(data.error || '凭证预览失败');
      status.textContent = '';
      results.replaceChildren(expenseRows(ctx, data, upload.name, source));
    } catch (e) {
      if (active === sequence) status.textContent = e.message;
    } finally {
      if (active === sequence) load.disabled = false;
    }
  }
  src.addEventListener('change', setSource);
  file.addEventListener('change', reset);
  dialog.addEventListener('close', () => { sequence++; }, { once: true });
  setSource();
}

function expenseRows(ctx, data, fileName, source) {
  const selected = new Set(data.rows.filter((r) => r.status === 'ready').map((r) => r.rowNumber));
  const total = node('strong', '');
  total.setAttribute('aria-live', 'polite');
  const save = btn(ctx, '核对入账', async () => {
    const rowNumbers = [...selected].sort((a, b) => a - b);
    await ctx.command('ops.importExpenses', { previewId: data.previewId, rowNumbers }, {
      title: '确认导入已支付的机构支出', target: sources[source] + ' · ' + fileName,
      fields: [['选中凭证', total.textContent]], confirmLabel: '确认入账',
    });
  }, 'primary');
  function sync() {
    const cents = data.rows.reduce((sum, r) => sum + (selected.has(r.rowNumber) && r.mode !== 'link' ? Math.round(100 * Number(r.amount)) : 0), 0);
    total.textContent = selected.size + ' 条凭证 · 新增支出 ' + money(cents / 100);
    save.disabled = !selected.size;
  }
  const ledger = table(ctx, {
    title: '凭证预览', rows: data.rows,
    filter: { label: '筛选核对结果', value: (r) => states[r.status] || '待核对' },
    cols: [
      { label: '入账', view: (r) => {
        if (r.status !== 'ready') return '—';
        const box = node('input');
        box.type = 'checkbox';
        box.setAttribute('aria-label', '选择第 ' + r.rowNumber + ' 行');
        box.checked = selected.has(r.rowNumber);
        box.addEventListener('change', () => {
          if (box.checked) selected.add(r.rowNumber);
          else selected.delete(r.rowNumber);
          sync();
        });
        return box;
      } },
      { label: '行 / 日期', view: (r) => named('第 ' + r.rowNumber + ' 行', r.date || '') },
      { label: '交易', view: (r) => named(r.payee || '未识别收款方', r.note || r.category || '') },
      { label: '金额', view: (r) => r.amount == null ? '—' : money(r.amount) },
      { label: '凭证', view: (r) => named(r.invoiceNo || r.voucher || '—', r.transactionId || '') },
      { label: '核对结果', view: (r) => node('div', 'fx-profile', [
        badge(ctx, states[r.status] || '待核对', r.status === 'ready' ? 'green' : r.status === 'review' ? 'amber' : 'neutral'),
        node('small', 'fx-muted', r.reason || ''),
      ]) },
    ],
  });
  sync();
  return node('section', 'fx-profile', [ledger, node('div', 'dialog-actions', [total, save])]);
}
