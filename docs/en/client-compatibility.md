# Browser and mini-program delivery

[Documentation](README.md) · [中文](../client-compatibility.md)

Deploy one HTTPS site. Staff and families sign in at `/?workspace=1`. Visitors can open `/visit`, `/roomtour` and `/faq` directly. The mobile app and mini-programs use the same web workflows. Each host has its own sign-in session. The server checks the active account and its institutional scope.

## Verification matrix

Run future browser, mini-app and device acceptance only against Simplified Chinese test institutions and Chinese builds. Shared host capabilities are in scope. [Repository testing scope](../../AGENTS.md)

Checks on 26 November 2026 used synthetic accounts and temporary databases. Browser runs used loopback. Verify production DNS and the certificate chain from the target devices.

| Client | Verified here | On-site acceptance |
| --- | --- | --- |
| Desktop Chrome | Official Chrome for Testing 158.0.8127.88 on Linux. Exercised desktop navigation, permissions and tabs for the owner, reception and finance accounts | Managed devices, printers and card readers |
| Mobile Chrome | Same Chrome engine at 390 × 844 with touch emulation. Exercised nurse, family and registered visitor routes and restricted records | Android hardware, keyboard, photos, microphone and system navigation |
| Safari | Real WebKitGTK 2.52.6 at 1440 and 390 pixels. Signed in, opened the resident registration form, navigated to beds and read the authenticated revision | Safari on macOS, iPhone and iPad, including microphone access, camera, downloads and returning from the background |
| WeChat mini-program | Generated the native source project. Tested configured entry routes, invalid configurations, retries and the public share target. Includes a native opt-in tour callback page | Institution AppID, verified business and request domains, official IDE build and a device trial |
| Douyin mini-program | Generated native TTML, TTSS, JavaScript and platform manifests. Tested entry routes and retries | Institution AppID, verified domain, official IDE build and a device trial |
| Android and iOS app | Expo exported both Hermes release bundles. An HTTPS origin opens the workspace sign-in page. The Android wrapper handles WebView history | Signed installation, keyboard, system back and media permissions |
| Electron | Uses the shared H5 workspace. See the client guide for desktop packaging and prior checks | OS-specific signing, installation and peripherals |

[Chrome for Testing](https://developer.chrome.com/docs/automation-and-testing/chrome-for-testing) · [Desktop and mobile client guide](../clients.md)

## Prepare a native project

Use Node.js 18 or newer. Run the appropriate command from the repository root. Supply the institution's verified origin and real platform AppID. Choose a new output directory. The output includes native pages, scripts, styles and platform manifests for the official IDE. Only the public AppID and origin are needed here.

```bash
node clients/build-miniapp.cjs wechat "$INSTITUTION_HTTPS_ORIGIN" "$WECHAT_APP_ID" .local/release-wechat
node clients/build-miniapp.cjs douyin "$INSTITUTION_HTTPS_ORIGIN" "$DOUYIN_APP_ID" .local/release-douyin
```

1. Configure the institution's HTTPS business domain in the corresponding console. Serve the platform-issued verification file at that domain's root under its original filename. A reverse proxy can serve the file directly. Check DNS, the certificate chain and the final sign-in origin from a phone. WeChat's native callback request also requires the registered request domain. [Tencent domain setup](https://cloud.tencent.com/document/practice/1301/100434) · [Douyin domain verification](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/tutorial/basic-ability/web-view-component/)
2. Import the output directory into the official IDE. The launch page is `pages/home/index`. It defaults to the workspace. Launch with `entry=visit`, `entry=tour` or `entry=faq` for the public website, tour or FAQ. Where the host exposes a share callback, the project returns the public visitor page. [Douyin project configuration](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/framework/general-configuration)
3. In a device trial, check anonymous browsing, staff sign-in, family scope, reconnecting after network loss and sign-out. WeChat phone callbacks require the platform entitlement and visitor consent. In-app Douyin payment requires a Douyin native payment page. The project currently offers the institution's billing interface and existing collection channels. A Douyin native payment integration is pending. [WeChat callback setup](../clients.md#roomtour-访客回电) · [Douyin web-view payments](https://developer.open-douyin.com/docs/resource/zh-CN/mini-app/develop/component/open-capacity/web-view)

## Voice, files and repeatable checks

The assistant records on hosts that provide microphone access, AudioContext and AudioWorklet. Text input is available when capture is unavailable or declined. The mobile wrapper declares the applicable microphone and photo permissions. Test image selection, PDF and Excel downloads, audio playback, system navigation and reconnecting on the actual devices. Staff review submissions. Confirm payments from the payment provider's receipt.

```bash
export NH_DEPLOYMENT_LANGUAGE=zh-CN
node --test tests/miniapp-clients.test.cjs
BROWSER_BIN=/path/to/chrome python3 tests/browser/workspace_roles.py
BROWSER_BIN=/path/to/chrome python3 tests/browser/public_visitors.py
python3 tests/browser/webkit_workspace.py
```

The WebKit check needs a GTK display, PyGObject and WebKit2GTK 4.1. Set `WEBKIT_PYTHON` to the Python installation with those bindings. It opens an offscreen window with an ephemeral session.

### Offline mini-app language

Pass the institutional locale after the output directory, for example `node clients/build-miniapp.cjs wechat https://care.example wx123456789abcdef0 /tmp/wechat-fr fr`, or set `NH_DEPLOYMENT_LANGUAGE`. The default is Simplified Chinese. The native home title, sharing title, missing-domain message, connection errors and retry label are bundled in Chinese, English, French or Spanish. Other registered international locales use English fallback. Only Chinese WeChat builds include the native mainland phone callback page. International visitors use the H5 visit page. Device acceptance for the Chinese release also requires each vendor’s devices and deployment settings.

Set `EXPO_PUBLIC_DEPLOYMENT_LANGUAGE` to choose the Expo app’s native connection and retry messages. Once connected, the H5 workspace uses the server's institutional locale and business edition. Electron uses `NH_DEPLOYMENT_LANGUAGE` at launch for native dialogs and microphone permission prompts in the same four languages.
