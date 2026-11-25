import React, { useEffect, useRef, useState } from 'react';
import { registerRootComponent } from 'expo';
import { BackHandler, Platform, SafeAreaView, StatusBar, StyleSheet, Text, View, Pressable } from 'react-native';
import { WebView } from 'react-native-webview';

const configured = process.env.EXPO_PUBLIC_WORKSPACE_URL || '';
const locale = process.env.EXPO_PUBLIC_DEPLOYMENT_LANGUAGE || 'zh-CN';
const offlineWords = {
  'zh-CN': ['未连接机构服务', '需要配置机构服务', '请检查网络或机构服务地址后重试。', '构建时请设置 EXPO_PUBLIC_WORKSPACE_URL 为机构 HTTPS 地址。', '重新连接'],
  en: ['Workspace unavailable', 'Workspace address missing', 'Check the connection and the workspace address.', 'Set EXPO_PUBLIC_WORKSPACE_URL to the institution’s HTTPS address when building the app.', 'Reconnect'],
  fr: ['Service indisponible', 'Adresse du service manquante', 'Vérifiez la connexion et l’adresse du service.', 'Définissez EXPO_PUBLIC_WORKSPACE_URL avec l’adresse HTTPS de l’établissement lors de la compilation.', 'Réessayer'],
  es: ['Servicio no disponible', 'Falta la dirección del servicio', 'Compruebe la conexión y la dirección del servicio.', 'Configure EXPO_PUBLIC_WORKSPACE_URL con la dirección HTTPS de la institución al compilar.', 'Volver a conectar'],
};
const words = offlineWords[locale] || offlineWords[locale.split('-')[0]] || offlineWords.en;
function institutionUrl(raw) {
  try {
    const url = new URL(raw);
    if (url.protocol === 'https:' && !url.username && !url.password) return url;
  } catch {}
  return null;
}

const target = institutionUrl(configured);
if (target?.pathname === '/' && !target.search && !target.hash) target.searchParams.set('workspace', '1');

function MobileWorkspace() {
  const web = useRef(null);
  const canGoBack = useRef(false);
  const [generation, retry] = useState(0);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (Platform.OS !== 'android') return;
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      if (!web.current || !canGoBack.current) return false;
      web.current.goBack();
      return true;
    });
    return () => subscription.remove();
  }, []);
  const reconnect = () => {
    canGoBack.current = false;
    setFailed(false);
    retry((i) => i + 1);
  };
  return (
    <SafeAreaView style={styles.screen}>
      <StatusBar barStyle="dark-content" backgroundColor="#f3f6fc" />
      {!target || failed ? (
        <View style={styles.state}>
          <Text style={styles.title}>{target ? words[0] : words[1]}</Text>
          <Text style={styles.copy}>
            {target ? words[2] : words[3]}
          </Text>
          {target && (
            <Pressable onPress={reconnect} style={styles.button}>
              <Text style={styles.label}>{words[4]}</Text>
            </Pressable>
          )}
        </View>
      ) : (
        <WebView
          ref={web}
          key={generation}
          source={{ uri: target.href }}
          style={styles.web}
          // Evaluate every scheme with our same-origin policy instead of forwarding unknown schemes to the OS.
          originWhitelist={['*']}
          javaScriptEnabled
          domStorageEnabled
          allowFileAccess={false}
          mixedContentMode="never"
          thirdPartyCookiesEnabled={false}
          setSupportMultipleWindows={false}
          allowsBackForwardNavigationGestures
          onNavigationStateChange={page => { canGoBack.current = page.canGoBack; }}
          onShouldStartLoadWithRequest={(r) =>
            r.url === 'about:blank' || institutionUrl(r.url)?.origin === target.origin
          }
          onHttpError={(event) => {
            if (event.nativeEvent.url === target.href) setFailed(true);
          }}
          onError={() => setFailed(true)}
        />
      )}
    </SafeAreaView>
  );
}
const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#f3f6fc', paddingTop: StatusBar.currentHeight || 0 },
  web: { flex: 1 },
  state: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 28, gap: 12 },
  title: { fontWeight: '600', fontSize: 22, color: '#172b50' },
  copy: { fontSize: 16, color: '#536581' },
  button: {
    backgroundColor: '#2457b7',
    paddingHorizontal: 20,
    paddingVertical: 10,
    borderRadius: 8,
  },
  label: { color: 'white' },
});
registerRootComponent(MobileWorkspace);
