# CareOps Agent SaaS

A multi-agent workspace for residential and integrated medical care. Staff can ask about a shift, dictate a care observation or upload the documents from a visit. The assistant uses records within the caller’s scope and opens drafts for staff to review and sign.

[Documentation](docs/en/README.md) · [Deploy an institution](docs/en/quick-deploy.md) · [Agent handbook](docs/en/agent-handbook.md) · [简体中文](README.md)

## Try a shift handover

| Ask or upload | What to expect |
| --- | --- |
| “How are things today?” | Occupancy, outstanding care work, recorded health exceptions and receipts available to your account. |
| Open a resident’s daily summary | Meals, activities and care from that resident’s signed records, with evidence references. |
| Upload visit photos or a registration worksheet | Confirm the person and document type, open a prefilled form and review it before saving. |

![The Chinese workspace showing a shift summary alongside occupancy, care tasks and a link to the inventory ledger](docs/previews/agent-workspace.webp)

*Captured from the Chinese demo with fictional records and a simulated model response.*

The main assistant handles conversation. Care and supply specialists can look up evidence for a handover. Scheduled rounds use the institution’s configured interval to prepare individual summaries from signed care records and documented observations. Staff can follow each summary back to its source. [Agent handbook](docs/en/agent-handbook.md)

## Run locally

Start with Linux, Python 3.11 or newer, the SQLCipher development library and Poppler. From the repository root, create a fictional institution in a separate database. The first interactive launch prompts for the `owner` account password.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-storage.txt -r requirements-payments.txt -r requirements-harness.txt -r requirements-a2a.txt
NH_DEPLOYMENT_LANGUAGE=en python server.py --db .local/careops-demo-en.sqlite3 --initial-data demo --port 8765
```

Open the [local workspace](http://localhost:8765/?workspace=1) and select **AI** or **Health assistant**. You can browse sample records, beds and work orders before configuring paid services. Model answers, OCR and voice need an enabled provider. Start a production installation with an empty encrypted database, HTTPS and separate recovery keys. [Service configuration](docs/en/deployment-console.md) · [Production deployment](docs/en/quick-deploy.md)

## Find your guide

| Goal | Start here |
| --- | --- |
| Admit a resident, sign care work, handle a payment or arrange a visit | [Staff and family manual](docs/en/workspace-manual.md) |
| Connect MCP tools, reuse skills or publish a read-only A2A capability | [Agent development and integration](docs/en/README.md#agent-development-and-integration) |
| Set permissions, connect devices, back up or upgrade | [Deployment and operations](docs/en/README.md#deployment-and-operations) |
| Prepare a licensed institution for acceptance | [Clinical readiness](docs/en/medical-commercial.md) |

Select the institution’s locale at installation. Additional languages inherit international names, addresses, hospital search and Google Maps. China deployments use Amap. Release testing covers Simplified Chinese and shared, language-independent behavior. [Test scope](AGENTS.md) · [Project log](LOG.md)
