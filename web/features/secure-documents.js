import { btn, facts, node, records, section, table } from './shared.js';

const endpoint = '/api/secure-documents/';
const limit = 16 * 1024 * 1024;

async function post(action, body, type) {
  const response = await fetch(endpoint + action, {
    method: 'POST',
    headers: { 'Content-Type': type },
    body,
  });
  if (!response.ok) {
    const failure = await response.json();
    throw new Error(failure.error || '文件处理失败');
  }
  return response;
}

export async function downloadDocument(ctx, source) {
  try {
    const response = await post(
      'export',
      JSON.stringify(source),
      'application/json',
    );
    const url = URL.createObjectURL(await response.blob());
    const link = node('a');
    link.href = url;
    link.download =
      (source.kind === 'referral'
        ? '院外转介-' + source.exportId
        : '民政报送-' + source.id + '-v' + source.version) + '.akdoc';
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    await ctx.refreshWorkspace();
    ctx.toast('已导出加密文件，收件人需登录本机构工作台查看');
    return true;
  } catch (error) {
    ctx.toast(error.message || '文件导出失败');
    return false;
  }
}

function documentView(ctx, source, data) {
  if (source.kind === 'referral') {
    const labels = {
      residentName: '长者姓名',
      destination: '接收单位',
      channel: '接收渠道',
      handoff: '交接类型',
      date: '交接日期',
      consentScope: '本人授权范围',
      summary: '交接摘要',
      allergies: '过敏记录',
      risk: '关注事项',
      referralId: '转介编号',
      exportId: '导出凭证',
      version: '数据格式版本',
    };
    return facts(
      Object.entries(labels)
        .filter(([key]) => key in data)
        .map(([key, label]) => [label, data[key]]),
    );
  }
  const metrics = data.serviceMetrics;
  return node('div', 'fx-profile', [
    facts([
      ['报送月份', data.month],
      ['版本', String(data.version || 1)],
      ['记录数', String(data.recordCount)],
      ['数据截止', data.cutoff],
      ['生成日期', data.createdAt],
      ['校验状态', data.status],
      ...Object.entries(data.summary || {}).map(([key, value]) => [
        key,
        String(value),
      ]),
    ]),
    metrics &&
      section(
        '照护运营汇总',
        facts([
          ['计划工单', String(metrics.scheduledTasks)],
          ['完成工单', String(metrics.completedTasks)],
          ['实际服务长者', String(metrics.servedResidents) + ' 人'],
        ]),
      ),
    section(
      '校验项目',
      records(data.checks || [], (text) => text),
    ),
    section(
      '待补正项目',
      records(data.issues || [], (text) => text, '当前版本已通过校验'),
    ),
    table(ctx, {
      title: '报送数据集',
      rows: data.rows || [],
      cols: [
        { label: '档案编号', view: (row) => row.residentId },
        { label: '入住日期', view: (row) => row.admittedAt },
        { label: '退住日期', view: (row) => row.dischargedAt || '—' },
        { label: '状态', view: (row) => row.status },
      ],
    }),
  ]);
}

export function openDocumentButton(ctx) {
  return btn(ctx, '打开加密文件', () => {
    const picker = node('input');
    picker.type = 'file';
    picker.accept = '.akdoc';
    picker.onchange = async () => {
      const file = picker.files[0];
      if (!file) return;
      if (file.size > limit) return ctx.toast('业务文件须在 16 MiB 以内');
      try {
        const response = await post('open', file, 'application/octet-stream');
        const { source, data } = await response.json();
        await ctx.refreshWorkspace();
        const session = await ctx.get('/api/version');
        if (session.userId !== ctx.state.user.id)
          throw new Error('会话已切换，请重新选择文件');
        ctx.detail(
          source.kind === 'report' ? '民政报送文件' : '院外转介文件',
          documentView(ctx, source, data),
        );
      } catch (error) {
        ctx.toast(error.message || '文件查阅失败');
      }
    };
    picker.click();
  });
}
