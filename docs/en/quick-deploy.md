# Deploy an institution

[Documentation](README.md) · [中文](../quick-deploy.md) · [Owner console](deployment-console.md) · [Clinical readiness](medical-commercial.md) · [User manual](workspace-manual.md)

Use a separate instance, domain, service account, database and recovery keys for each contracted institution. Configure branches and staff access within that instance. A systemd service behind a TLS reverse proxy serves desktop and mobile browsers and the mobile app shells.

## 1. Prepare a host

These commands assume an apt-based Linux host with systemd and Python 3.11 or newer. Install your reviewed release in /opt/care-workspace. Rehearse upgrades and rollback on a Simplified Chinese staging installation.

```sh
sudo apt-get install python3-venv python3-dev build-essential pkg-config libsqlcipher-dev poppler-utils caddy
sudo useradd --system --user-group --home-dir /var/lib/care-workspace --shell /usr/sbin/nologin care-workspace
sudo install -d -m 700 -o care-workspace -g care-workspace /var/lib/care-workspace
sudo install -d -m 750 /etc/care-workspace
cd /opt/care-workspace
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements-storage.txt -r requirements-payments.txt -r requirements-harness.txt -r requirements-a2a.txt
sudo install -m 600 deploy/linux/service.env.example /etc/care-workspace/service.env
sudoedit /etc/care-workspace/service.env
```

Set NH_PUBLIC_ORIGIN to the institution's HTTPS origin. Set NH_DEPLOYMENT_LANGUAGE to en, zh-CN, fr or es. Initialization fixes this choice in the encrypted database. Existing Chinese installations remain Chinese. Each institution can deploy its own locale. The China edition uses Amap. Other locales inherit Google Maps from the international edition. Configure the institution's map provider for online hospital suggestions. Submit only the hospital name or city and review the selection. Original clinical text, names and staff notes stay in their original language. The current finance ledger uses CNY and Shanghai business dates. Institutions requiring other accounting currencies, time zones or tax rules need a local acceptance review.

## 2. Initialize and start

This example creates an English licensed-medical installation. Set the same profile and language in the service environment. For residential care, use residential. The initialization command prompts for the first Owner password and requires a new database path.

```sh
sudo -u care-workspace .venv/bin/python manage_deployment.py init --db /var/lib/care-workspace/institution.sqlite3 --profile licensed-medical --language en
sudo -u care-workspace .venv/bin/python manage_deployment.py check --db /var/lib/care-workspace/institution.sqlite3 --profile licensed-medical --language en --public-origin https://care.example.org --full
sudo install -m 644 deploy/linux/care-workspace.service /etc/systemd/system/care-workspace.service
sudo systemctl daemon-reload
sudo systemctl enable --now care-workspace.service
```

Add your site's hostname and upstream port to Caddy using the supplied Caddyfile.example. Validate the proxy configuration and reload it. Once DNS and TLS are ready, check the public service.

```sh
curl --fail https://care.example.org/api/health
curl --fail https://care.example.org/api/public/deployment
journalctl -u care-workspace.service -n 60
```

The staff workspace is at /?workspace=1 and the visitor website at /visit. Sign in as owner using the password set at initialization. Open System management → Deployment to review the model, plan, listener and device connections. Managed customers use their platform plan. Operators who run their own credentials can explicitly enable NH_DEPLOYMENT_MODE=operator at service startup. When a port is pinned in systemd, update the listener and proxy together. Follow the client guide for WeChat and Douyin domain registration, app identifiers and release approval. [Client compatibility](client-compatibility.md)

## 3. Commission and recover

Run acceptance in an isolated Simplified Chinese (`zh-CN`) installation. Use test accounts to exercise admission, beds, care signatures, role and branch isolation, payment reconciliation and alert receipts. Use synthetic documents to test OCR, Agent drafts and billing receipts. Keep the snapshot recovery key, external platform vault keys and device credentials under separate custody. Business snapshots exclude external credentials. Practice restoring originals and operational records on a separate host. Document offsite targets, snapshot intervals, recovery time and downtime contacts. The signed updater verifies a full snapshot before changing versions. Commission each live model, messaging service, payment terminal and clinical device with its supplier. [Owner operations](deployment-console.md) · [Agent integration](agent-handbook.md)

### Locales and business rules

A new institution may select zh-CN, en, fr or es. French and Spanish include starter translations for sign-in, navigation and names. Remaining interface messages use English. Theme and typeface are personal preferences. The institution locale stays fixed.

To ship another locale, add its tag and display name to the [locale manifest](../../web/assets/deployment-locales.json) and supply a web/assets/locales/<tag>.json interface catalogue. The international edition is the default for additional languages and includes global hospital lookup, Google Maps and international names and postal addresses. The China edition selects Amap and the domestic directory. The browser loads local catalogues and preserves original resident data. Ship locale changes in a signed release. Repository regression and browser acceptance use only the Simplified Chinese edition and language-independent cases. Inspect the effective installation at /api/public/deployment. For online suggestions set NH_GOOGLE_PLACES_KEY or NH_AMAP_WEB_KEY in the service environment.

### Hospital map services

Staff can enter the hospital as printed on the original encounter record. The China edition's local directory prioritizes Henan. Its online search uses AMap. International editions use Google Places to search worldwide in the deployment language. Staff can open a public map search without a service key. [AMap search URI](https://lbs.amap.com/api/uri-api/guide/search/search) · [Google Maps search URLs](https://developers.google.com/maps/documentation/urls/get-started)

For results inside the form, enable AMap Web Service and set `NH_AMAP_WEB_KEY` for China, or enable Places API (New) with billing and set `NH_GOOGLE_PLACES_KEY` for an international deployment. Keep keys on the server and restrict each key to its API and your server addresses. Restart the service after changing provider settings. For Chinese acceptance, use a public or synthetic hospital name to check its address, the Amap browser handoff and the provider receipt. Manual chart entry is available offline. [AMap Places search](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch) · [Google Places Text Search](https://developers.google.com/maps/documentation/places/web-service/text-search)

The desktop client opens staff-selected hospital map links in the system browser. Results are displayed temporarily for verification. The Google Maps attribution image is the unmodified `GoogleMaps_Logo_DarkGray_2x.png` from Google's official asset bundle. Its use alongside Places results is governed by Google's attribution rules. The project licence grants no rights to the Google Maps trademark. [Google Maps attribution policy](https://developers.google.com/maps/documentation/places/web-service/policies) · [Official attribution assets](https://developers.google.com/static/maps/documentation/images/Google_Maps_Attribution_Assets.zip)
