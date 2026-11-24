import { named, node, section, records } from './shared.js';

export async function previewSummary(ctx, resident, openDocument) {
  let draft;
  try {
    draft = await ctx.get('/api/residents/' + encodeURIComponent(resident.id) + '/summary-draft');
  } catch (error) {
    ctx.toast(error.message);
    return;
  }
  const form = node('form', 'fx-profile');
  const text = node('textarea', 'fx-input');
  text.rows = 6;
  text.maxLength = 3000;
  text.required = true;
  text.value = draft.summary;
  const confirmed = node('input');
  confirmed.type = 'checkbox';
  confirmed.required = true;
  const submit = node('button', 'btn btn-primary', '签认并保存摘要');
  submit.type = 'submit';
  form.append(
    section(
      '摘要依据',
      records(draft.evidence, (e) => {
        const row = node('div', 'fx-profile', [named(e.label, e.value)]);
        const details = node('details', '', [
          node('summary', 'fx-muted', '来源编号'),
          node('code', '', e.id)
        ]);
        row.append(details);
        const doc =
          e.source === 'dossier_documents' && ctx.state.medicalDocuments.find((d) => d.id === e.id);
        if (doc) {
          const button = node('button', 'btn btn-text', '核对已签文书');
          button.type = 'button';
          button.onclick = () => openDocument(ctx, doc);
          row.append(button);
        }
        return row;
      })
    ),
    node('label', 'field', [node('span', '', '核对后的档案摘要'), text]),
    node('label', 'fx-agreement', [confirmed, '我已核对长者身份和上述记录，并确认保存此次摘要。']),
    submit
  );
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (submit.disabled || !form.reportValidity()) return;
    submit.disabled = true;
    try {
      await ctx.command('dossier.signSummary', {
        residentId: resident.id,
        fingerprint: draft.fingerprint,
        summary: text.value,
        confirmed: confirmed.checked
      });
    } finally {
      submit.disabled = false;
    }
  });
  ctx.detail('核对' + resident.name + '的动态档案摘要', form);
}
