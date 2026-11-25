const labels = {
  'zh-CN': {app:'医养管理平台', invalid:'机构服务需要 HTTPS 地址，或本机开发地址', offline:'未连接机构工作台', reconnect:'请先启动机构服务，并核对 NH_APP_URL 配置。',
    microphone:'允许此工作台窗口使用麦克风吗？', purpose:'用于按住说话和语音转写。', allow:'允许使用', cancel:'取消', startup:'无法启动'},
  en: {app:'Care Management', invalid:'Use an HTTPS workspace address or a local development address.', offline:'Workspace unavailable', reconnect:'Start the service and check NH_APP_URL.',
    microphone:'Allow this workspace to use the microphone?', purpose:'Used for push-to-talk and transcription.', allow:'Allow', cancel:'Cancel', startup:'Unable to start'},
  fr: {app:'Gestion des soins', invalid:'Utilisez une adresse HTTPS ou une adresse locale de développement.', offline:'Service indisponible', reconnect:'Démarrez le service et vérifiez NH_APP_URL.',
    microphone:'Autoriser cet espace à utiliser le microphone ?', purpose:'Pour la dictée et la transcription.', allow:'Autoriser', cancel:'Annuler', startup:'Démarrage impossible'},
  es: {app:'Gestión asistencial', invalid:'Utilice una dirección HTTPS o una dirección local de desarrollo.', offline:'Servicio no disponible', reconnect:'Inicie el servicio y compruebe NH_APP_URL.',
    microphone:'¿Permitir que este espacio utilice el micrófono?', purpose:'Para el dictado y la transcripción.', allow:'Permitir', cancel:'Cancelar', startup:'No se pudo iniciar'},
};
const locale = process.env.NH_DEPLOYMENT_LANGUAGE || 'zh-CN';
module.exports = labels[locale] || labels[locale.split('-')[0]] || labels.en;
