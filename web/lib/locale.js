// Presentation follows the deployment locale. Currency and business time zones
// continue to use the institution's recorded settings.
export const displayLocale = globalThis.NH_DEPLOYMENT?.language || 'zh-CN';
export const interfaceText = text => globalThis.NH_I18N?.text(text) ?? text;
