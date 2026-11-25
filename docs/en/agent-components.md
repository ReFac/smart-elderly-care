# Who handles each assistant task

[Documentation](README.md) · [简体中文](../agent-components.md)

You can ask the health assistant which beds are available while DeerFlow prepares a resident’s visit record in the background. Each worker sees the evidence for its own task. The institution service makes the model calls and records the usage receipts.

| Workflow | Component responsible | Staff control |
| --- | --- | --- |
| Ask a question by voice or keyboard, look up a record or open a filtered page | The workspace transcribes speech and makes the tools your account can use available to DeerFlow. Its conversation graph runs the authorised steps and returns an answer or a button. | Click the button to open the page. Review and confirm any change there. |
| Upload records from one visit | The workspace takes the originals, runs OCR and suggests a type for each document. Files uploaded from a saved chat action can share that turn’s usage ID. | Check the types, choose the resident and select an existing visit or start a new one. |
| Prepare a visit draft | The workspace saves the originals before it queues the job. The pinned DeerFlow graph reads the evidence it has permission to use, requests a metered model call and checks the source references. | Open the job in the assistant’s document tasks, compare the draft with the originals, edit it and sign to file it. |
| Review daily life and health changes | The institution scheduler selects the residents and periods to review. Each of the two DeerFlow workflows reads the evidence authorised for that review. | Inspect the sources behind each entry. The workspace checks clinical access and consent for delivery to family members. |
| Correct the way the assistant answers | For supported corrections, the workspace proposes a versioned rule and shows its effect on synthetic examples. Once approved, the conversation and drafting workers can read the rule within its approved scope. | An authorised reviewer decides whether to publish the rule and can later roll it back. The project draws on Hermes skill practices and includes an adapted Hermes XLSX skill. [Skill provenance](../../skills/UPSTREAM.md) |

Cross-department briefs start with `agent.start`. The cloud model chooses from the account’s authorised care, inventory and finance specialists, or staff can select one directly. DeerFlow’s `SubagentExecutor` runs each selected specialist’s assigned read. The institution service checks its scope and uses the evidence to prepare a draft for staff review. Chat, visit documents and scheduled summaries have their own DeerFlow workflows. [Conversation loop](../../deploy/deerflow/conversation.py) · [Specialist delegation](../../deploy/deerflow/delegation.py)

## Operations

When you submit documents, the job stays with your account. The worker checks your original session, current role and assignment to the resident. Pending jobs survive a process restart. If your session expires, sign in again to resume a job you still have permission to handle. When the job finishes, its unsigned draft is ready for your review.

The assistant can also suggest a writing change from earlier reviews. It reads the last 40 approved or rejected suggestions for the selected campus and topic. Staff see their own review history. Reviewers can draw on the history for campuses where they have review authority. The input excludes feedback text, staff identifiers and resident information. The embedded DeerFlow SDK checks the proposed skill against its previous version and reports its release and content digest in the preview. Staff can preview the change on a fictional example, and a reviewer decides whether to publish it.

Install ByteDance’s DeerFlow `v2.2.0` SDK from commit `58fc5bd5b8e6ea46538e9481ba06ca2a46e14e2a` in the isolated worker environment. Open the Owner deployment console to check the installed version and open your document tasks or the rounds schedule. Expand a conversation or draft receipt to see the runtime and task ID recorded for that work. To trace a job’s model and media receipts, select its task ID under Institution settings → AI usage → Call details. Some older entries have no task ID. [Deployment](quick-deploy.md) · [Worker setup](../../deploy/deerflow/README.en.md) · [Upstream release](https://github.com/bytedance/deer-flow/releases/tag/v2.2.0)

A conversation can draw on up to five eligible, complete exchanges from the same account and access scope. Approved campus writing rules carry over to future conversations and drafts within their scope. In the review history, open a proposal’s evidence to compare the original and submitted rules, read the static review report and inspect any review history used to suggest the change.

To connect a community MCP server, an operator registers the server, permitted tools, argument limits and account grants in `NH_MCP_CONFIG`. The assistant offers tools the employee can use. DeerFlow checks that the remote server declares the selected tool read-only. External applications calling the facility API also need an authorised institution account. [Connection guide](agent-handbook.md#extend-with-an-existing-mcp-or-community-skill) · [DeerFlow MCP client](../../deploy/deerflow/capabilities.py)

## Token use per task

A direct text question can take one model call. When the model asks for a register, DeerFlow dispatches the authorised read. The model sees the result and decides whether to reply or request another read, up to three calls to tools over the whole turn. For example, it can check stock before requesting a calculation or open one of the examples listed in a skill. Each model response has its own metered receipt. For a visit draft, the model matches numbered lines from the original to form fields. OCR is billed by page. The service can reuse a successful OCR receipt for the same original. A scheduled health review skips the model call if the evidence and rules for that resident, stay and day still match the previous review.

The question, the extracts the model may read and the length of its answer all affect token use. Select a task ID to see the employee’s cached input, uncached input and output. OCR, ASR and read-aloud each have their own usage units. [Owner controls](deployment-console.md)
