import React, { useState } from 'react';
import { registerRootComponent } from 'expo';
import { SafeAreaView, StatusBar, StyleSheet, Text, View, Pressable } from 'react-native';
import { WebView } from 'react-native-webview';

const configured = process.env.EXPO_PUBLIC_WORKSPACE_URL || '';
function institutionUrl(raw) {
  try {
    const url = new URL(raw);
    if (url.protocol === 'https:' && !url.username && !url.password) return url;
  } catch {}
  return null;
}

function MobileWorkspace() {
  const target = institutionUrl(configured);
  const [generation, retry] = useState(0);
  const [failed, setFailed] = useState(false);
  const reconnect = () => {
    setFailed(false);
    retry((i) => i + 1);
  };
  return (
    <SafeAreaView style={styles.screen}>
      <StatusBar barStyle="dark-content" backgroundColor="#f3f6fc" />
      {!target || failed ? (
        <View style={styles.state}>
          <Text style={styles.title}>{target ? '未连接机构服务' : '需要配置机构服务'}</Text>
          <Text style={styles.copy}>
            {target
              ? '请检查网络或机构服务地址后重试。'
              : '构建时请设置 EXPO_PUBLIC_WORKSPACE_URL 为机构 HTTPS 地址。'}
          </Text>
          {target && (
            <Pressable onPress={reconnect} style={styles.button}>
              <Text style={styles.label}>重新连接</Text>
            </Pressable>
          )}
        </View>
      ) : (
        <WebView
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
