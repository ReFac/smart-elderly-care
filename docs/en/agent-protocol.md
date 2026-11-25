# Read-only A2A service

[中文](../agent-protocol.md)

A partner agent can use A2A 1.0 JSON-RPC to query available beds or today's care workload. Each skill reads the caller's authorized operational records and returns aggregate counts and a task ID. Public discovery contains interface information only.

| Operation | Endpoint or method | Result |
| --- | --- | --- |
| Discover | `GET /.well-known/agent-card.json` | Service URL, skills and session authentication |
| Send | `POST /api/a2a`, `SendMessage` | Completed task with timestamp and a text artifact |
| Retrieve | `GetTask` | Same account and current scope required, also after a restart |
| Cancel | `CancelTask` | Both skills complete synchronously. A terminal task returns `-32002` |

Install `python -m pip install -r requirements-a2a.txt` in the server's Python environment and restart. Set the production HTTPS origin. An installation without the optional SDK returns HTTP 503 for A2A. Authenticate a dedicated staff account through `POST /api/auth/login` and retain its session cookie in the client. Keep credentials out of messages and logs. The account needs assistant access plus the requested business permission. The workspace determines campus and assignment scope. Public visitors and family accounts cannot read institutional tasks.

Send one `text/plain` part with `bed-availability` for visible bed, vacant bed and occupied bed counts. Send `today-care-work` to count today's work by status. Attachments, external URLs, tenant selectors, resident records, webhooks and business mutations are unsupported.

```json
{"jsonrpc":"2.0","id":"read-123","method":"SendMessage","params":{"message":{"messageId":"schedule-123","role":"ROLE_USER","parts":[{"text":"today-care-work"}]}}}
```

Read the task ID from `result.task.id`. Retain the message ID on retry. A conflicting reuse of a request or message ID is rejected. Each retrieval checks the caller's institution, account and current access scope. Submit a fresh query if the assignment or permissions have changed.

```json
{"jsonrpc":"2.0","id":"get-123","method":"GetTask","params":{"id":"replace-with-task-id"}}
```

Run `python tests/run.py -p test_agent_protocol.py` to exercise the official client over loopback, including discovery, authentication, sending, retrieval and sign-out. The suite also checks concurrent retries, conflicting IDs, restart recovery and authorization changes. The Agent Card advertises synchronous queries and does not enable streaming or push notifications. [A2A 1.0 specification](https://a2a-protocol.org/v1.0.0/specification/) · [Official Python SDK](https://github.com/a2aproject/a2a-python)
