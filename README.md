# ResearchGuard

ResearchGuard 0.3 is a stateful multi-agent council that converts a research question into a
reviewed experimental protocol. LangChain tool-calling agents and deterministic CI agents
share a LangGraph workflow. The graph dispatches evidence work in parallel, revises
weaknesses, pauses for human approval, and stores every state in SQLite or PostgreSQL.

## Why this is multi-agent

Each specialist owns a distinct artifact and evaluation criterion. The skeptical reviewer
can send the proposal through a bounded revision cycle; a human must approve the resulting
protocol before completion. This makes disagreement, recovery, and governance visible in
the execution trace.

```text
question → planner ─┬→ PubMed worker ──┐
                    ├→ Crossref worker ├→ evidence gate → hypothesis → methods → statistics
                    └→ fallback worker ┘                                      ↓
                                    ethics review → statistics → skeptic → synthesis
                                           ↓                       ↑             ↓
                                  ethics interrupt           revision ← human approval
```

## Quick start

Python 3.11–3.13 is recommended (some AI dependencies may not yet support Python 3.14).

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev,openai]'
pytest
researchguard run "Does an AI tutor improve algebra transfer for first-year students?"
researchguard-api
```

Demo mode is deterministic, offline, and requires no API key. To enable live structured
agent calls, copy `.env.example`, export the variables, and set `RESEARCHGUARD_MODE=live`.
Live agents can call PubMed, Crossref, citation verification, abstract retrieval, claim
support screening, and statistical tools. A DOI/PMID check alone is insufficient: each claim
also receives a supporting passage and entailment score before entering shared state. Failed
sources retry and then route through an explicit local-corpus recovery node.

LangSmith tracing works through the standard `LANGSMITH_*` environment variables. Run
`researchguard-eval` to create a 24-question hosted dataset and run both the multi-agent
council and a one-pass single-agent baseline. Grounding, design-safety, and collaboration
evaluators make the value of review and revision measurable.

For a credential-free, reproducible benchmark, run
`python -m researchguard.local_eval` (`researchguard-local-eval` after reinstalling the package). The committed
[evaluation results](docs/evaluation-results.md) report 24/24 end-to-end task completions for
both systems, while collaboration value is 24/24 for the council and correctly marked not
applicable for the credible single-agent baseline. This deterministic result measures workflow
orchestration and governance, not live-model or external-source quality. The focused
[three-minute walkthrough](docs/three-minute-walkthrough.md) provides a presentation script.

Open `http://127.0.0.1:8000` after starting `researchguard-api`. The FastAPI dashboard shows
the live node timeline, evidence table, entailment scores, protocol diffs, and durable
approve/reject interrupt. Human feedback becomes a concrete study safeguard in the next
revision. Reports export as Markdown. API docs are available at `/docs`.

The frontend is maintained separately from the API under `src/researchguard/web/`:

```text
web/
├── index.html   # semantic page structure and accessible dialogs
├── tokens.css   # shared spacing, type, radius, motion, and shadow primitives
├── styles.css   # responsive core layout, focus states, and reduced motion
├── enhancements.css # trust, collaboration, presentation, role, and mobile components
├── i18n.js      # message catalog ready for additional locales
└── app.js       # rendering, live SSE updates, voice, decisions, and recovery actions
```

The interface includes a branching workflow graph, a plain-language progress list, protocol
overview cards, grouped agent timings, field-level revision diffs, evidence filtering and
sorting, score explanations, prominent synthetic-source labels, and dedicated loading,
failure, ethics-review, approval, cancellation, and completion states. Long-running graph
updates use server-sent events and pause while the tab is hidden.

The workspace also supports recent-run resume/archive/delete actions with undo, shareable
resume links, run-to-run and revision comparisons, searchable evidence and audit events,
clickable graph-node inspection, evidence provenance trails, uncertainty indicators, and
human protocol edits that automatically re-enter skeptical review. System/dark/light themes,
mobile graph condensation, skeleton loading states, optional review notifications and sound,
and first-run onboarding round out the accessible interface.

For trusted local HTTPS (required when microphone access is tested outside the browser's
localhost exception), generate a localhost certificate and set
`RESEARCHGUARD_SSL_CERTFILE` plus `RESEARCHGUARD_SSL_KEYFILE`. ResearchGuard validates that
both files exist and then passes them to Uvicorn. Keep private keys out of version control.

For demonstrations and deeper review, the interface adds a full-screen presentation story,
an at-a-glance run scorecard, explicit specialist disagreement and resolution cards,
evidence-to-protocol claim tracing, and first-draft versus current-protocol comparison. A
keyboard command palette (`Ctrl/Command+K`), high-contrast mode, actionable empty states,
workspace reset, and Markdown/JSON/print-to-PDF exports support both presentation and daily
use. Privacy-safe interaction analytics remain in local browser storage and retain only the
latest 100 product events; no question or protocol content is recorded.

Progressive disclosure provides a focused simple view and a fully inspectable expert view.
Researcher, ethics, statistician, and administrator roles emphasize relevant artifacts without
changing the underlying audit record. Reviewers can bookmark evidence, save filter presets,
leave and resolve targeted comments, use an approval-readiness checklist, and work from an
activity inbox. Mobile users can open a dedicated workflow timeline, while stage estimates
distinguish slow work from stalled execution. Shared spacing, typography, motion, radius, and
shadow values live in `web/tokens.css`.

The [moderated usability test](docs/usability-test.md) provides participant tasks, success
criteria, observation guidance, and a local feedback-export workflow for three to five real
sessions.

The [UX release checklist](docs/release-ux-checklist.md) covers VoiceOver/NVDA, keyboard-only
operation, 200% zoom, reduced motion, physical iPhone/Android checks, live timing calibration,
privacy verification, and feature-freeze sign-off. The in-app privacy center explains server,
browser, and external-provider data flows and provides browser-data export and deletion.

Browser coverage uses Playwright on desktop and mobile Chromium, with Axe checks that fail on
serious or critical accessibility violations and committed screenshots that detect visual
regressions:

```bash
npm install
npx playwright install chromium
npm run test:e2e
```

The **Guided showcase** button launches a deterministic walkthrough with parallel research,
a simulated database outage, fallback recovery, statistical critique and repair, ethics
review, human feedback, report export, and a single-agent comparison. The animated topology
and append-only audit timeline make every transition visible.

Voice works without provider keys in supported browsers: Record question and Live dictation use
the browser's built-in Speech Recognition, and spoken briefings use `speechSynthesis`. The
captured audio is used only during the browser session and is not uploaded or saved. Safari and
Chrome provide the expected Speech Recognition implementation; unsupported browsers show a
clear fallback message. Set `ELEVENLABS_API_KEY` only when you need server-side transcription,
Scribe v2 streaming, or hosted audio generation.
Set `RESEARCHGUARD_API_KEY` to require the `X-ResearchGuard-Key` header on API routes.

## Local-project security scope

ResearchGuard is designed for local coursework, portfolio review, and controlled
demonstrations—not public or multi-tenant deployment. The optional shared API key and demo user
ID provide lightweight separation only; they are not production authentication. Do not enter
real participant records, protected health information, confidential research data, or reused
credentials.

## Model Context Protocol (MCP)

ResearchGuard includes a local stdio MCP server built with the official Python MCP SDK v2.
It exposes six read-only tools for evidence search, claim-support screening, citation checks,
sample-size estimation, saved-run listing, and protocol inspection; it also exposes an about
resource, a protocol resource template, and a governed-study prompt. Approval, protocol edits,
archive, and deletion are intentionally not MCP tools and remain human-controlled in the web app.

Start the server directly with:

```bash
python -m researchguard.mcp_server
```

Normally an MCP host starts that command over stdio rather than a person running it manually.
Copy `mcp.json.example`, replace its absolute paths, and add the resulting server definition to
your MCP-compatible host. Use `mcp dev src/researchguard/mcp_server.py` to inspect the tools
interactively. The MCP process should use the same `RESEARCHGUARD_DB` value as the web app if it
needs to inspect saved runs.

The local build still applies a restrictive dashboard Content Security Policy and basic browser
security headers, limits voice uploads by type and size, blocks non-HTTP evidence links, bounds
API inputs, checks run ownership, and uses constant-time shared-key comparison. `.env`, local
databases, virtual environments, build output, browser traces, and dependency folders are
excluded from version control. Set `RESEARCHGUARD_MAX_VOICE_UPLOAD_BYTES` to change the default
10 MB recording limit.

Before sharing the project, scan the working tree and repository history for API keys. Only
`.env.example` should be committed. If any real key has ever been committed or shown in a demo,
revoke and replace it rather than merely deleting the text.

Run the consolidated, non-destructive local check before sharing:

```bash
researchguard-security-check
```

It scans text files for likely credential formats without printing matched values, verifies
sensitive `.gitignore` entries and loopback binding, checks built wheels for `.env` or database
files, runs the Python suite, and invokes npm and Python dependency audits when their tools are
available. Warnings identify optional or unavailable checks; confirmed secrets, unsafe package
contents, configuration failures, test failures, and high-severity dependency findings return a
nonzero exit status. Use `--skip-tests` or `--skip-audits` for an offline quick check.

For production persistence, set `RESEARCHGUARD_DB` to a `postgresql://...` URL. The service
uses LangGraph's PostgreSQL checkpointer, applies its schema, tracks thread ownership, supports
concurrent background runs, and exposes retention cleanup in the service layer. SQLite runs
in WAL mode for local demonstrations. Rate limits and user ownership are enforced by the API.

## Container deployment

Run the application and PostgreSQL together:

```bash
docker compose up --build
```

The image runs as a non-root user and includes a readiness-based health check. `/health`
reports process health and `/ready` verifies database connectivity. GitHub Actions runs Ruff,
the complete test suite with coverage, and a container build on pushes and pull requests.

## Guided showcase

1. Click **Guided showcase** and watch the animated graph.
2. Observe one evidence worker fail while verified parallel evidence allows recovery.
3. Inspect the ethics assessment and the statistician's initial enrollment estimate.
4. Watch the skeptical reviewer identify missing attrition inflation and trigger repair.
5. Reject the protocol with “Add weekly adverse-event monitoring.”
6. Confirm that exact requirement appears in the protocol diff, then approve it.
7. Export the evidence report and inspect the single-agent comparison scorecard.

## Operational notes

- External evidence retrieval is metadata/abstract based; paywalled full text is not bypassed.
- The lexical entailment tool is a screening layer, not a substitute for expert source review.
- Put the API behind HTTPS and a managed identity provider for public deployment.
- Run retention cleanup according to institutional data-governance policy.

This project generates research decision support, not medical advice. Consequential studies
should receive domain-expert and ethics review.
