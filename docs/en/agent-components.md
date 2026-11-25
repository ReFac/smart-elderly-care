# Who handles each assistant task

[Documentation](README.md) · [简体中文](../agent-components.md)

Staff can ask about available beds while a separate worker organises a visit. Pi owns the conversation. DeerFlow 2.0 owns the scoped evidence workflow. The institution service calls the configured model and records its receipts.

| Workflow | Component responsible | Staff control |
| --- | --- | --- |
| Voice or keyboard questions, read-only tools and filtered navigation | The workspace transcribes speech and supplies authorised tools. The Pi SDK runs the conversation loop and returns the answer or a button. | The staff member opens the destination and confirms any business change. |
| Upload a group of visit records | The workspace handles original files, OCR and initial classification. Uploads from a saved Pi action can share that turn’s usage ID. | Choose the resident, review document types and select the visit or start a new one. |
| Prepare a visit draft | The workspace saves the originals and queues the job. The pinned DeerFlow 2.0 graph reads scoped evidence, requests metered generation and validates source references. | Open the assistant’s document tasks, inspect originals, edit the draft and sign to file it. |
| Review daily living and health | The institution scheduler selects residents and work periods. The two DeerFlow workflows read their own authorised evidence. | Staff can inspect source references. Clinical permissions and family delivery consent are checked by the workspace. |
| Improve responses after a correction | The workspace turns supported corrections into versioned candidate rules and provides synthetic examples for comparison. Approved rules can be read by Pi and DeerFlow within the applicable scope. | An authorised reviewer can publish or roll back a rule. The project draws on Hermes skill practices and distributes an adapted Hermes XLSX skill. [Skill provenance](../../skills/UPSTREAM.md) |

## Operations

A document job belongs to its submitting staff member. The worker rechecks the original session, current role and resident assignment. Pending work survives a process restart. After their session expires, staff can sign in and resume an eligible job. A completed background task leaves an unsigned draft for review.

The Owner deployment console shows the Pi and DeerFlow installation status. Open Institution settings → AI usage → Call details and select a task ID to view its model and media receipts. Legacy rows can have an empty task ID. Install the locked Pi package and the isolated official ByteDance `v2.0.0` worker from commit `7e7f0410797693cf882594555ba414e0361d4c6f`. [Deployment](quick-deploy.md) · [Worker setup](../../deploy/deerflow/README.en.md) · [Upstream release](https://github.com/bytedance/deer-flow/releases/tag/v2.0.0)

## Token use per task

A direct text question can take one model call. When the model requests a register lookup, Pi dispatches the authorised tool and uses the results to compose an answer. For visit documents, the model assigns numbered source lines to fields. OCR is metered by page, and a successful receipt for the same original can be reused. A scheduled health review skips generation when the evidence and rules for the same resident, stay and day have not changed.

Actual token counts depend on the question, authorised extracts and reply length. Usage separates cached input, uncached input and output. OCR, ASR and read-aloud retain their own units. Open a task ID to inspect the employee’s receipts. [Owner controls](deployment-console.md)
