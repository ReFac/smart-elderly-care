// This text must work before the H5 service is reachable.
const locales = {
  'zh-CN': { app:'医养管理平台', home:'机构工作台', share:'参观养老机构', offline:'机构工作台暂时无法访问', missing:'尚未配置机构业务域名',
    offlineHint:'请核对网络和小程序后台的业务域名。', missingHint:'请由机构管理员配置经过校验的 HTTPS 工作台地址。', retry:'重新连接' },
  en: { app:'Care Management', home:'Care workspace', share:'Visit our care home', offline:'Workspace unavailable', missing:'Workspace address missing',
    offlineHint:'Check your connection and the business domain registered for this mini app.', missingHint:'Ask your administrator to configure the verified HTTPS address.', retry:'Reconnect' },
  fr: { app:'Gestion des soins', home:'Espace de soins', share:'Visiter la résidence', offline:'Espace de soins indisponible', missing:'Adresse du service manquante',
    offlineHint:'Vérifiez votre connexion et le domaine enregistré pour cette mini-application.', missingHint:'Demandez à votre administrateur de configurer l’adresse HTTPS vérifiée.', retry:'Réessayer' },
  es: { app:'Gestión asistencial', home:'Espacio asistencial', share:'Visitar la residencia', offline:'Servicio no disponible', missing:'Falta la dirección del servicio',
    offlineHint:'Compruebe la conexión y el dominio registrado para la miniaplicación.', missingHint:'Solicite al administrador que configure la dirección HTTPS verificada.', retry:'Volver a conectar' },
};
function nativeText(language = 'zh-CN') {
  if (language === 'zh-CN') return locales['zh-CN'];
  const base = String(language).split('-')[0].toLowerCase();
  return Object.prototype.hasOwnProperty.call(locales, base) ? locales[base] : locales.en;
}
module.exports = {nativeText};
