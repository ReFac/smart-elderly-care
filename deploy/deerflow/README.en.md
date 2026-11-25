# DeerFlow conversation and evidence workers

[Documentation](../../docs/en/README.md) · [简体中文](README.md)

For each visit document extraction, daily-life summary or health review, CareOps creates a fresh graph with ByteDance’s DeerFlow v2.2.0 SDK factory. The worker runs in a separate Python process. The institution service sends it only the evidence authorised for that task over private pipes. Its one read-only tool supplies this evidence to the configured cloud model. The worker checks the draft’s references against the original evidence before returning it.

DeerFlow also runs staff conversations. The conversation worker can ask for the tools available to the signed-in account while a separate worker prepares a document. The conversation runtime also reads approved skills, invokes configured read-only MCP tools and checks candidate writing rules before staff publish them. The institution service checks who signed in and which beds and residents they may access. It handles OCR, billing, original files, approval and audit. [Pinned upstream source](https://github.com/bytedance/deer-flow/tree/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a)

For a skill lookup, the controller gives DeerFlow’s `describe_skill` a catalogue filtered to the employee’s role. For example, a lookup can return `/mnt/skills/public/xlsx/SKILL.md`. The native `read_file` tool reads a temporary copy of that one approved document. It can also read a listed Markdown example or a range of lines. The host checks paths, permissions and file type before making a copy. Skill declarations cannot grant shell or write access. [Upstream skill catalogue and tool](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/backend/packages/harness/deerflow/skills/describe.py)

From the repository root on Linux, use Git and Python 3.12 or newer to install the worker.

```bash
python3.12 -m venv .local/deerflow-venv
.local/deerflow-venv/bin/python -m pip install -r deploy/deerflow/requirements.txt
.local/deerflow-venv/bin/python -m pip install --no-deps -r deploy/deerflow/sdk.txt
python3 tests/run.py -p test_deerflow_worker.py
```

The first requirements file installs the dependencies the graph imports. The second installs the pinned upstream SDK (2.2.0) and its extension API (0.2.9) from the same commit. The full gateway, media and document-service packages are outside this deployment. The test uses synthetic Chinese evidence and a simulated provider. To use a separately managed environment, set `NH_DEERFLOW_PYTHON` to the interpreter’s absolute path. Restart the institution service after you install or change the interpreter.

If the SDK is missing, the worker cannot accept a conversation or produce a draft. Scheduled jobs wait for retry. Open the Owner deployment console to check the local installation. To check the runtime for a completed conversation or draft, expand its receipt in the workspace.

For managed installations, keep `NH_DEERFLOW_BACKEND=deerflow` or leave it unset. Replace any old `direct` setting before restarting. The readiness check verifies the versions, source commit, package subdirectories and imports required by the embedded graphs. Run it from the institution service’s Python environment.

```bash
python3 -c 'from platform_core.agents.deerflow_worker import installation; print(installation())'
```

A conversation can use up to three authorised reads. The deployed model requests each tool through its native tool-calling API. DeerFlow dispatches the request. The institution service checks permission, supplies the result and records the receipt for the model’s next decision. Each result carries the ID of the call that produced it. The conversation worker communicates through a private pipe, without access to the provider’s credentials. [Conversation graph](conversation.py) · [Evidence graph](worker.py)

## Review a proposed writing rule

In the assistant, open **改进回答** and choose the campus and topic. **从审核记录提议** asks for a draft based on the last 40 accepted or rejected suggestions in that scope. Staff can use their own decisions. A reviewer can use decisions from a campus where they have review authority. The model sees section order, outcomes and counts. It receives neither the original feedback nor resident records. The same controls are available under institution settings in **平台 AI 套餐 → 管理助理写作规则**.

Previewing, submitting, approving and restoring a version each run the embedded checks. Under **审核与记录 → 查看审核依据**, compare the exact candidate with its base version and read the SDK’s static report (`deerflow.skill-review.report.v1`). Suggestions based on earlier decisions also show anonymous counts. A staff reviewer can approve or reject the proposal or restore an earlier version. Chat and scheduled work read only the campus’s approved version from its encrypted database. A static review covers the proposed skill text. Clinical outcomes and runtime behaviour need their own checks. The embedded deployment uses the SDK’s `validate_candidate` and skill review checks. Operating the upstream Gateway’s `stage`, `check` and `commit` workflow separately requires a POSIX host, a shared local skills directory, persistent database-backed run events and an enabled security-scanning model. [Upstream Skill Evolution deployment requirements](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/docs/skill-evolution-host.md)

## Publish a reviewed rule to an optional Gateway

Install the [Gateway extension](gateway_extension.py) if the institution wants to publish an approved writing rule as a custom DeerFlow skill. The workspace and Gateway must share one POSIX host. Store skills on the local filesystem and set `run_events.backend` to `db` on a persistent Gateway database. Use a single Gateway process with SQLite. Enable static scanning and verify that the security-scanning model can receive and check candidate skill text. Each institution needs its own deployment. [Gateway host requirements](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/docs/skill-evolution-host.md#enable-deliberately)

1. Set `NH_EXPERIENCE_GATEWAY=1` in the workspace service environment and restart the service. Create a separate Gateway account for each campus. In that account create and enable a custom skill, for example `careops-meals`. Its directory may contain only one non-executable `SKILL.md`. Include the same skill name and a description in its frontmatter.
2. Put `gateway_extension.py` on a read-only import path for the Gateway interpreter. Merge the example below into its `config.yaml`, replacing the account, campus and port. Add `careops-handover`, `careops-visit` or `careops-observations` to the target list for the other supported topics. Restart the Gateway and enable `careops.reviewed-skills` in its plugin settings.
3. In a signed-in workspace session, a reviewer for that campus calls `POST /api/assistant/learning/gateway-ticket` with `{"campusId":"campus-main","topic":"meals","version":1,"gatewayOwner":"gateway-care-lead","confirm":true}`. Use the version currently approved for the campus. The returned `ticket` authorises one reviewed rule for five minutes. Signing out, losing review permission, approving another version or issuing another ticket invalidates it.
4. In the target Gateway account’s authenticated browser session, send `ticket`, `threadId` and `runId` to `POST /api/plugins/careops.reviewed-skills/actions/stage`. Use a successful interactive `lead_agent` run in that account with sealed evidence. The extension checks the candidate bytes and asks the Gateway to review them. The response contains `proposalId`, `decision`, `candidateHash` and the workspace digest. The two hashes cover different package formats.
5. After review, use the same Gateway account to send `ticket`, `proposalId` and `confirm: true` to `POST /api/plugins/careops.reviewed-skills/actions/publish`. If the ticket has expired, obtain another for the current version. Publishing rechecks review authority, version and scan outcome. The receipt includes `operationId`, `publication`, `views` and `generation`. Repeating the request returns the original operation. Recover an incomplete operation by its ID. [Gateway recovery](https://github.com/bytedance/deer-flow/blob/58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a/docs/skill-evolution-host.md#publication-recovery-and-rollback)

```yaml
plugins:
  - name: careops-reviewed-skills
    use: gateway_extension:install
    config:
      workspace_port: 8765
      owner_campuses: {gateway-care-lead: campus-main}
    host_access:
      evidence:
        owners: [gateway-care-lead]
      skill_mutations:
        owners: [gateway-care-lead]
        operations: [stage, check, commit]
        trigger_agents: [lead_agent]
        target_skills: [careops-meals]
        topology: single_host_local
```

Sync is off by default. The extension accepts an authenticated human browser session and exposes no publishing tool to the model. The integration regression checks publication and idempotent retries with a temporary SQLite database, real Gateway host services and a simulated scan result. Verify the deployed Gateway with the institution’s own scanning account before handing it over.
