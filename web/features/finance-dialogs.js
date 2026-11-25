import { btn, node } from './shared.js';

// All financial writes still go through the normal form validation and confirmation.
export function financeContext(ctx) {
  if (ctx.financePanel) return ctx;
  return {
    ...ctx,
    financePanel: true,
    dialog(options) {
      const box = ctx.dialog(options);
      if (box?.matches?.('dialog')) box.classList.add('finance-drawer');
      return box;
    },
    detail(title, content, actions) {
      const box = ctx.detail(title, content);
      if (box?.matches?.('dialog')) {
        box.classList.add('finance-drawer');
        box.append(
          node('footer', 'dialog-actions finance-actions', [btn(ctx, '关闭', () => box.close()), actions]),
        );
      }
      return box;
    },
  };
}
