# Owner deployment console

Sign in as Owner and open **部署控制台** in the main sidebar. The console reports the running release, facility profile, chat provider, model, credential availability, paid plan, gateway heartbeat times and change history. Actual access to a model also depends on the upstream account, plan and connectivity.

## Installation modes

| Host setting | Access |
| --- | --- |
| `NH_DEPLOYMENT_MODE=managed` (default) | A customer Owner can inspect the platform plan, view usage and register facility gateways. Only the platform operator can supply provider credentials or endpoints. |
| `NH_DEPLOYMENT_MODE=operator` | A trusted Owner of a dedicated process can stage model credentials, endpoints, listener settings and activation policy. |
| `NH_INSTITUTION_PROFILE=licensed-medical` | Displays the licensed medical profile. The default profile is residential care. |

Use one service process, encrypted business database and operations store per facility. After provisioning the Owner password and database keys, a managed installation behind an HTTPS reverse proxy can start with:

```bash
NH_DEPLOYMENT_MODE=managed python3 manage_updates.py run --initial-data empty --db .local/institution.sqlite3 --public-origin https://care.example.org
```

For an operator installation, choose **编辑部署配置**. DeepSeek, OpenAI, Anthropic and Google use known official endpoints. For a private OpenAI-compatible service, provision its full chat completions URL in the host's comma-separated `NH_DEPLOY_CHAT_ENDPOINTS`. HTTPS and loopback HTTP are supported. A custom destination needs a dedicated credential. Leaving the password field blank retains the credential for the same provider and endpoint. Official endpoints may also use host credentials. Chat, OCR and speech have distinct adapters. See [provider configuration](../provider.md) and [media setup](../media.md).

## Apply a change

1. Set the target model and port. The default listener uses loopback. For a container or protected reverse-proxy network, explicitly set both `NH_DEPLOY_ALLOW_NETWORK_BIND=1` and a valid `--public-origin` before binding all interfaces. Restrict backend connectivity to the trusted proxy.
2. Save a draft for separate approval, or select application at next restart. A running service continues serving its current connection. The Owner can withdraw a pending change.
3. During a maintenance window restart the whole launcher or managed system service, then update reverse-proxy upstream settings if the port changed. An explicit CLI `--port` pins the port and takes precedence. Omit it to use the saved setting.
4. Verify the running values, release and audit entry after restarting. If a port is occupied or an approved endpoint has been removed, use the previous known-good CLI port to correct an incompatible pending port, or temporarily boot in managed mode with host credentials and a fixed port to recover the operations store offline.

Deployment settings are stored in a separate SQLCipher file next to the business database, named `.<database filename>.deployment.sqlite3`. Its separate key defaults to the same directory and can be set with `NH_PLATFORM_KEY_FILE`. Business snapshots exclude deployment settings and credentials. Back up the operations file and encryption key separately during controlled downtime and verify recovery. The web API never returns provider or gateway credentials.

## Gateway heartbeat

Register a gateway ID, name, edge transport and a device-specific random bearer token of 32–128 characters using letters, digits, underscores or hyphens. Disable the gateway or rotate its token to revoke the previous credential. A gateway should send a heartbeat every minute using HTTPS or same-host loopback:

```http
POST /api/deployment/gateways/radar-1/heartbeat
Authorization: Bearer <device token>
Content-Type: application/json

{}
```

A successful reply includes `accepted` and the server receipt timestamp. The console distinguishes waiting for the first heartbeat, a verified heartbeat within three minutes, expired connectivity and disabled gateways. Refresh the page status for a fresh sample. MQTT or Modbus gateways must bridge this HTTP heartbeat at the edge. Vendor event delivery, bed assignment and care alerts require separate integration testing.
