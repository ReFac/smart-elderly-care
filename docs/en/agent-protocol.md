# Read-only A2A service

[Documentation](README.md) · [中文](../agent-protocol.md)

A partner agent can ask how many beds are free or how much care work is due today over A2A 1.0 JSON-RPC. Each skill counts only the operational records its caller can read and returns those counts with a task ID. Public discovery describes the interface.

| Operation | Endpoint or method | Result |
| --- | --- | --- |
| Discover | `GET /.well-known/agent-card.json` | Service URL, skills and session authentication |
| Send | `POST /api/a2a`, `SendMessage` | Completed task with timestamp and a text artifact |
| Retrieve | `GetTask` | Only the original account with the same current scope can retrieve the task, including after a restart |
| Cancel | `CancelTask` | Both skills complete synchronously. A terminal task returns `-32002` |

Run `python -m pip install -r requirements-a2a.txt` in the server’s Python environment, set the production HTTPS origin and restart. Without the optional SDK the A2A endpoint returns HTTP 503.

Sign in a dedicated staff account through `POST /api/auth/login` and keep the session cookie in the client. Keep credentials out of messages and logs. Give the account assistant access and the business permission for the query. The workspace applies its campus and assignment restrictions. Visitors and family members cannot retrieve institution tasks.

Send a single `text/plain` part. Use `bed-availability` to count visible, vacant and occupied beds, or `today-care-work` for today’s workload by status. The service does not accept attachments, external URLs, tenant selectors, resident records, webhooks or requests to change business records.

```json
{"jsonrpc":"2.0","id":"read-123","method":"SendMessage","params":{"message":{"messageId":"schedule-123","role":"ROLE_USER","parts":[{"text":"today-care-work"}]}}}
```

Read the task ID from `result.task.id`. Retry with the same message ID. The server rejects reusing a request or message ID for a conflicting request. Every retrieval checks the institution, account and current access scope. If the caller’s assignment or permissions change, send a fresh query.

```json
{"jsonrpc":"2.0","id":"get-123","method":"GetTask","params":{"id":"replace-with-task-id"}}
```

Run `python tests/run.py -p test_agent_protocol.py` to use the official client over loopback. It exercises discovery, sign-in, sending, retrieval and sign-out, as well as concurrent retries, conflicting IDs, recovery after restart and changes to permissions. The Agent Card advertises synchronous queries only. Streaming and push notifications are disabled. [A2A 1.0 specification](https://a2a-protocol.org/v1.0.0/specification/) · [Official Python SDK](https://github.com/a2aproject/a2a-python)
