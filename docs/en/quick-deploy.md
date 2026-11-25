# Deploy an institution

[Documentation](README.md) · [中文](../quick-deploy.md) · [Owner console](deployment-console.md) · [Clinical readiness](medical-commercial.md) · [User manual](workspace-manual.md)

Give each contracted institution its own instance, domain, service account, database and recovery keys. Set up the branches and assign staff access inside that instance. The same systemd service, behind a TLS reverse proxy, serves desktop and mobile browsers and the mobile app shells.

## 1. Prepare a host

Start with an apt-based Linux host, systemd and Python 3.11 or newer. Install Python 3.12 or newer for the isolated DeerFlow worker. Put the reviewed release in /opt/care-workspace. Use a Simplified Chinese staging installation to rehearse upgrades and rollback.

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

Set NH_PUBLIC_ORIGIN to the institution’s HTTPS origin. Choose en, zh-CN, fr or es for NH_DEPLOYMENT_LANGUAGE before initialisation. The encrypted database keeps that choice for the life of the instance. Each institution makes its own selection. Existing Chinese installations keep Chinese.

The China edition uses Amap. Other locales inherit Google Maps from the international edition. Configure the appropriate map provider for online hospital suggestions. Search by hospital name or city only and check the selected result. Names, staff notes and original clinical text keep their original language. The finance ledger uses CNY and Shanghai business dates. If an institution needs another accounting currency, time zone or tax regime, review those requirements during local acceptance.

Install the pinned DeerFlow worker for staff conversations, visit documents and rounds. Before commissioning, check the installed SDK version in the Owner deployment console. [Worker setup](../../deploy/deerflow/README.en.md) · [Component responsibilities](agent-components.md)

A signed update includes the DeerFlow worker, its configuration and dependency manifests. If the locks match, the updater reads dependencies offline from the original installation. Before admitting traffic, the candidate release runs a synthetic DeerFlow conversation and starts the evidence worker. This check needs neither cloud credentials nor institution records. If it fails, the updater restores the previous version and its snapshot.

When upgrading a managed installation whose launcher still requires both older runtimes, first run the new release’s `manage_updates.py verify-package --manifest <path>` with the institution’s trusted signing configuration. Then start its launcher with `run --install-root <original-installation>` and keep the existing database and service arguments. This lets the new launcher validate the signed package against the original deployment and restore its prior release if needed.

When a release changes a dependency lock, set `NH_AGENT_RUNTIME_STORE` to an absolute path that the service account can read. In `deerflow/<sha256-of-requirements.txt-followed-by-sdk.txt>/`, place both original manifests and the prepared `venv/bin/python`. For the DeerFlow hash, concatenate the original file bytes in that order. Keep the current and previous dependency directories available for rollback. Only the deployment operator needs write access.

## 2. Initialize and start

For this English licensed-medical installation, use the same profile and language in the service environment as in the command. Use residential for a residential care institution. Provide a new database path. Initialisation prompts for the first Owner password.

```sh
sudo -u care-workspace .venv/bin/python manage_deployment.py init --db /var/lib/care-workspace/institution.sqlite3 --profile licensed-medical --language en
sudo -u care-workspace .venv/bin/python manage_deployment.py check --db /var/lib/care-workspace/institution.sqlite3 --profile licensed-medical --language en --public-origin https://care.example.org --full
sudo install -m 644 deploy/linux/care-workspace.service /etc/systemd/system/care-workspace.service
sudo systemctl daemon-reload
sudo systemctl enable --now care-workspace.service
```

Add the institution’s hostname and upstream port to Caddy using the supplied Caddyfile.example. Validate and reload the proxy configuration. Once DNS and TLS are ready, check the public endpoints and service log.

```sh
curl --fail https://care.example.org/api/health
curl --fail https://care.example.org/api/public/deployment
journalctl -u care-workspace.service -n 60
```

Staff sign in at /?workspace=1. Visitors use /visit. Sign in as owner with the password set at initialisation and open System management → Deployment to check the model, plan, listener and device connections. Managed customers use the platform plan. Operators who supply their own credentials can explicitly enable NH_DEPLOYMENT_MODE=operator at startup. If systemd pins the port, change the listener and proxy together. WeChat and Douyin also require domain registration, app identifiers and platform release approval. [Client compatibility](client-compatibility.md)

## 3. Commission and recover

Use an isolated Simplified Chinese (`zh-CN`) installation and test accounts to check admission, beds, care signatures, role and branch restrictions, payment reconciliation and alert receipts. Use fictional documents to test OCR, Agent drafts and billing receipts.

Keep the snapshot recovery key, external platform vault keys and device credentials under separate custody. Business snapshots exclude external credentials. Restore original files and operational records on a separate host. Record the offsite destinations, snapshot intervals, recovery time and whom to contact during downtime. The signed updater verifies a full snapshot before it changes versions. Commission each live model, messaging service, payment terminal and clinical device with its supplier. [Owner operations](deployment-console.md) · [Agent integration](agent-handbook.md)

### Locales and business rules

Choose zh-CN, en, fr or es when creating the institution. French and Spanish have starter translations for sign-in, navigation and names. Remaining interface messages use English. Staff can set their own theme and typeface. The installation language stays fixed.

To ship another locale, add its tag and display name to the [locale manifest](../../web/assets/deployment-locales.json) and supply a web/assets/locales/<tag>.json interface catalogue. The international edition is the default for additional languages and includes global hospital lookup, Google Maps and international names and postal addresses. The China edition selects Amap and the domestic directory. The browser loads local catalogues and preserves original resident data. Ship locale changes in a signed release. Repository regression and browser acceptance use only the Simplified Chinese edition and language-independent cases. Inspect the effective installation at /api/public/deployment. For online suggestions set NH_GOOGLE_PLACES_KEY or NH_AMAP_WEB_KEY in the service environment.

### Hospital map services

Enter the hospital name as it appears on the encounter record. The local directory in the China edition prioritises Henan, with AMap for online search. International editions use Google Places for worldwide results in the installation language. Staff can open a public map search without a service key. [AMap search URI](https://lbs.amap.com/api/uri-api/guide/search/search) · [Google Maps search URLs](https://developers.google.com/maps/documentation/urls/get-started)

For suggestions inside a form in China, enable AMap Web Service and set `NH_AMAP_WEB_KEY`. For international deployments, enable billing for Places API (New) and set `NH_GOOGLE_PLACES_KEY`. Keep each key on the server and restrict it to the relevant API and server addresses. Restart after changing provider settings. During Chinese acceptance, use a public or fictional hospital name to verify the address, the Amap link in the browser and the provider receipt. Staff can enter the chart manually offline. [AMap Places search](https://lbs.amap.com/api/webservice/guide/api-advanced/newpoisearch) · [Google Places Text Search](https://developers.google.com/maps/documentation/places/web-service/text-search)

When staff select a hospital map link in the desktop client, it opens in the system browser. Results appear temporarily for verification. Places results use Google’s unmodified `GoogleMaps_Logo_DarkGray_2x.png` attribution image from its official asset bundle. Google’s attribution rules govern its use. The project licence grants no rights to the Google Maps trademark. [Google Maps attribution policy](https://developers.google.com/maps/documentation/places/web-service/policies) · [Official attribution assets](https://developers.google.com/static/maps/documentation/images/Google_Maps_Attribution_Assets.zip)
