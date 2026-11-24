import { intake, residents, beds } from './residency.js';

import { assessments, care, medications } from './care.js';

import { longCare } from './long-care.js';
import { billing } from './billing.js';

import { inventory, shifts, reports } from './operations.js';

import { renderAccess } from './access.js';
import { accountCenter } from './account.js';
import { renderDossier } from './dossier.js';
import { renderGateways } from './gateways.js';
import { recentChanges } from './recent-changes.js';
import { activityPage } from './activity.js';

import { roomsPage, tourPage } from './rooms.js';

const features = {
  account: accountCenter,
  rooms: roomsPage,
  tour: tourPage,
  access: (ctx) => renderAccess('access', ctx),
  settings: (ctx) => renderAccess('settings', ctx),
  family: (ctx) => renderDossier('family', ctx),
  dossier: (ctx) => renderDossier('dossier', ctx),
  integrations: (ctx) => renderGateways('integrations', ctx),
  inbox: (ctx) => renderGateways('inbox', ctx),
  activity: activityPage,
  history: recentChanges,
  intake,
  residents,
  beds,
  assessments,
  care,
  medications,
  billing,
  longCare,
  inventory,
  shifts,
  reports,
};

export function renderFeature(route, ctx) {
  const render = features[route];
  if (!render) return ctx.ui.empty('未找到该工作页面');
  return render(ctx);
}
