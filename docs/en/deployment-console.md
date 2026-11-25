# Owner deployment console

[Documentation](README.md)

Sign in as Owner and open **部署控制台** in the sidebar. Check the running release, facility profile, chat provider and model here. The console also shows whether a credential is available, which paid plan is in use, when gateways last checked in and which settings changed. Under **Health assistant runtimes**, check the installed DeerFlow SDK, open your document tasks or the rounds schedule, and use a task ID to find its calls in AI usage. The installation check reads local dependencies. A model call also needs a working connection and an upstream account and plan that permit access.

## Installation modes

| Host setting | Access |
| --- | --- |
| `NH_DEPLOYMENT_MODE=managed` (default) | A customer Owner can inspect the platform plan, view usage and register facility gateways. Only the platform operator can supply provider credentials or endpoints. |
| `NH_DEPLOYMENT_MODE=operator` | A trusted Owner of a dedicated process can stage model credentials, endpoints, listener settings and activation policy. |
| `NH_INSTITUTION_PROFILE=licensed-medical` | Displays the licensed medical profile. The default profile is residential care. |

Give each facility its own service process, encrypted business database and operations store. For a managed installation behind an HTTPS reverse proxy, provision the Owner password and database keys before running this command.

```bash
NH_DEPLOYMENT_MODE=managed python3 manage_updates.py run --initial-data empty --db .local/institution.sqlite3 --public-origin https://care.example.org
```

In an operator installation, open **编辑部署配置** to change providers. DeepSeek, OpenAI, Anthropic and Google use known official endpoints and may use host credentials. To use a private OpenAI-compatible service, add its full chat completions URL to the host’s comma-separated `NH_DEPLOY_CHAT_ENDPOINTS`. Use HTTPS or loopback HTTP and a dedicated credential for that custom destination. Leave the password field blank to keep the credential for the same provider and endpoint. Chat, OCR and speech each use a separate adapter. [Provider configuration](../provider.md) · [Media setup](../media.md)

## Apply a change

1. Choose the model and port. By default the service listens on loopback. To bind all interfaces in a container or protected reverse-proxy network, first set `NH_DEPLOY_ALLOW_NETWORK_BIND=1` and a valid `--public-origin`. Allow only the trusted proxy to reach the backend.
2. Save the change for separate approval or choose to apply it on the next restart. Until then, the service uses its current connection. The Owner can withdraw a pending change.
3. During the maintenance window, restart the whole launcher or managed system service. If the port changed, update the upstream in the reverse proxy. An explicit CLI `--port` takes precedence over the saved value. Omit it to use the saved port.
4. Check the release, running settings and audit entry. If the new port is occupied, start with the previous working CLI port and correct the pending port. If an approved endpoint is gone or the operations store needs offline recovery, you can temporarily boot in managed mode with host credentials and a fixed port.

The SQLCipher file `.<database filename>.deployment.sqlite3` sits next to the business database and stores deployment settings. Its key is separate and defaults to the same directory. Set `NH_PLATFORM_KEY_FILE` to choose another key location. Business snapshots exclude deployment settings and credentials. During controlled downtime, back up the operations file and its key separately and verify that you can recover them. The web API never returns provider or gateway credentials.

## Gateway heartbeat

Register the gateway ID, name and edge transport. Give each device its own random bearer token of 32 to 128 letters, digits, underscores or hyphens. Rotating the token or disabling the gateway revokes the old credential. Have the gateway send a heartbeat every minute over HTTPS or same-host loopback.

```http
POST /api/deployment/gateways/radar-1/heartbeat
Authorization: Bearer <device token>
Content-Type: application/json

{}
```

A successful reply contains `accepted` and the time the server received the heartbeat. Refresh the console to see whether the gateway is waiting for its first heartbeat, has checked in within the past three minutes, has timed out or is disabled. Bridge MQTT or Modbus to this HTTP heartbeat at the edge. Test vendor event delivery, bed assignment and care alerts separately.
