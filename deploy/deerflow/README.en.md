# DeerFlow 2.0 evidence worker

[Documentation](../../docs/en/README.md) · [简体中文](README.md)

CareOps uses ByteDance’s DeerFlow v2.0.0 SDK factory to create a fresh graph for each medical document extraction, personal daily-life summary, or health review. Pi handles the staff conversation. The institution service owns logged-in identity, bed and resident scope, OCR, billing, source archives, approval and audit. The worker receives a single authorised projection through private pipes in its own Python process. Its one read-only tool supplies that evidence to the configured cloud model. Its final stage checks that the draft references the original evidence. [Pinned upstream source](https://github.com/bytedance/deer-flow/tree/7e7f0410797693cf882594555ba414e0361d4c6f)

Install from the repository root on Linux with Git and Python 3.12 or newer for the worker.

```bash
python3 -m venv .local/deerflow-venv
.local/deerflow-venv/bin/python -m pip install -r deploy/deerflow/requirements.txt
.local/deerflow-venv/bin/python -m pip install --no-deps -r deploy/deerflow/sdk.txt
python3 tests/run.py -p test_deerflow_worker.py
```

The first requirements file installs the imports used by this evidence graph. The second installs the pinned upstream SDK without its full gateway, media and document-service dependency set. The test command uses Chinese synthetic evidence and a simulated provider. Override `NH_DEERFLOW_PYTHON` with an absolute interpreter path for a separately managed environment. Restart the institution service after installing or changing the interpreter.

The default `NH_DEERFLOW_BACKEND=deerflow` reports an unavailable worker when its SDK is missing. Scheduled jobs wait for retry. For explicit operational rollback set `NH_DEERFLOW_BACKEND=direct` and restart the service. The usage ledger attributes direct requests to the platform. Returning to the default enables DeerFlow for new work.
