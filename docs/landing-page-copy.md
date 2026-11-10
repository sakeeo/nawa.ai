# NAWA.AI — Landing Page Copy (Draft v1)

Language: English (matches UI copy rule in `docs/design-system.md` §9). Indonesian version can follow with i18n.
Tone: calm, concrete, trustworthy. No claims the system cannot prove. Numbers marked `[TBD]` must come from the real evaluation report before launch.

---

## 1. Hero

**Eyebrow:** Self-hosted AI for your company

**Headline:** From business knowledge to intelligent execution.

**Subheadline:** NAWA.AI answers questions from your documents, analyzes your database in plain language, and runs work through AI agents with human approval. It all runs on your own servers. Your data never leaves.

**Primary CTA:** Try the live demo
**Secondary CTA:** View on GitHub

**Trust line:** Open source · One-command install · Works fully offline

---

## 2. Problem

**Heading:** Your company knows a lot. Finding it takes too long.

- Answers are scattered across documents, spreadsheets, and databases.
- Simple data questions still need someone who writes SQL.
- Reports and alerts are built by hand, every month.
- Teams use AI tools nobody controls or audits.
- And for many companies, sending documents to a third-party AI cloud is simply not allowed.

**Bridge line:** NAWA.AI gives you one assistant for all of it, inside your own walls.

---

## 3. Four capabilities

### Knowledge — Ask your documents
Upload SOPs, policies, contracts, and reports. Ask in plain language and get an answer with clickable citations to the exact passage. If the answer is not in your documents, NAWA.AI says so instead of guessing.

### Data — Ask your database
Ask "Which outlet sold the least in August?" No SQL needed. You see the query, the table, the chart, and an explanation. Every query is read-only, checked, and logged.

### Agents — Delegate the analysis
Ask a bigger question, like "Why did Bandung sales drop and what should we do?" A team of specialist agents splits the work, pulls from data and documents, and writes a report. Every step is traceable.

### Automation — Run it on schedule
Schedule monthly reports or stock alerts. Anything risky, like sending an email, waits in the Approval Center until a person says yes.

---

## 4. How it works (demo story)

**Heading:** One question leads to the next.

Using the fictional restaurant chain Resto Noesantara:

1. **"What is the procedure when a customer says the food is unfit?"** → Answer with citations to the SOP.
2. **"Which outlet had the lowest sales in August?"** → SQL, chart, and explanation.
3. **"Why did Bandung drop, and what do we do?"** → Agents combine sales by menu, ingredient stock, supplier contracts, and receiving SOPs into one report.
4. **"Send this every month-end."** → Scheduled, sent only after approval.

**CTA:** Watch the 3-minute demo

---

## 5. Privacy and control (key differentiator)

**Heading:** Your infrastructure. Your data. Your rules.

| | |
|---|---|
| **Runs on your servers** | On-premise or private cloud. Database, files, vector index, and logs stay with you. |
| **Local AI by default** | Open-weight models and local embeddings. External providers are off unless an admin turns them on. |
| **Air-gapped capable** | Offline mode blocks every outbound connection. |
| **No telemetry** | Nothing is sent out. Outbound traffic is logged and restricted. |
| **One install, one organization** | No self-signup. Admins invite users and set roles. |

---

## 6. Built to be trusted

**Heading:** AI you can check, not just AI that looks right.

- **Cited or declined.** Every answer shows its sources, or says it found none.
- **Safe SQL.** Single `SELECT` only, allowlisted tables, row limit, read-only role, timeout. Dangerous queries are blocked and logged.
- **Documents are data, not instructions.** Text hidden inside a file cannot take control of the assistant.
- **Humans approve risky actions.** Sending email, calling external APIs, and writing data all wait for approval.
- **Workspace isolation.** Teams only see their own data, enforced in the database itself.
- **Measured quality.** Every feature is scored against a golden dataset, including the failures. See the evaluation report.

**Proof strip** (fill with real numbers, never targets):
Retrieval Recall@5 `[TBD]` · Citation accuracy `[TBD]` · Dangerous queries blocked `[TBD]` · Unauthorized tool calls `[TBD]`

---

## 7. Install in one command

**Heading:** Running in minutes, not months.

```bash
git clone https://github.com/<user>/nawa-ai && cd nawa-ai
cp .env.example .env
docker compose --profile local-llm up -d
```

Then follow the setup wizard: create your admin, choose your AI provider, and optionally load demo data.

**Minimum:** 4 vCPU, 16 GB RAM, 50 GB disk.
**Recommended:** 8 vCPU, 32 GB RAM, 16–24 GB GPU.

---

## 8. Who it is for

- **Operations managers** find the right SOP in seconds.
- **Business owners** understand performance without writing SQL.
- **Analysts** get a full, sourced report from one instruction.
- **IT admins** keep control of access, cost, and audit.

---

## 9. FAQ

**Is NAWA.AI a SaaS?** No. You install it and run it yourself.

**Does my data go to an AI provider?** Not by default. Local models are the default. External providers work only if an admin enables them, and never in offline mode.

**Can it work without internet?** Yes, with models downloaded beforehand.

**Which models does it support?** Local models through Ollama or vLLM. Optional external providers through a single gateway.

**What if the answer is not in my documents?** It tells you it could not find it.

**Can the AI change my data?** No. SQL is read-only. Other risky actions need human approval.

**What is it built with?** Python/FastAPI, Next.js, PostgreSQL + pgvector, Redis, LangGraph, LiteLLM, Langfuse. All open source.

---

## 10. Final CTA

**Heading:** See it work on your own infrastructure.

**Subheadline:** Try the demo, or run it yourself in one command.

**Primary CTA:** Try the live demo
**Secondary CTA:** Read the docs

---

## Footer / meta

**Footer tagline:** NAWA.AI — Self-hosted Enterprise Intelligence & Automation Platform.

**Meta title:** NAWA.AI — Self-hosted AI for company knowledge, data, and automation
**Meta description:** Ask your documents, query your database in plain language, and automate work with AI agents. Self-hosted, offline-capable, human-approved. Your data never leaves.

---

## Open questions for the owner

1. Audience: recruiters/hiring managers (portfolio) or prospective clients? Current draft leans product-first with a portfolio-friendly proof section.
2. Live demo URL, GitHub URL, and demo video do not exist yet. CTAs are placeholders.
3. Proof numbers wait for Phase 1–4 evaluation. Do not publish targets as results.
4. Product name pronunciation or meaning ("nawa") not stated in the plan. Add a one-line origin if wanted.
