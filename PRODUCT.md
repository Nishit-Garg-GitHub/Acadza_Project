# Acadza Report-to-Fix: product and safety model

## Product architecture

The existing pipeline groups reports per question, screens student comments, runs deterministic record checks, asks a blind solver and a judge for structured proposals, then applies Python guards before routing each case. The judge never writes to the production question bank.

The optional FastAPI service adds validated report ingestion and SQLite persistence for reports, proposed decisions, faculty outcomes, and append-only audit events. The static review queue remains a demonstration backed by browser `localStorage`; its actions do not persist to the API. The Backend inbox is the connected workflow. Backend approval/rejection records a faculty decision only; publishing question-bank changes and sending student replies are separate, unimplemented production operations.

## Faculty workflow

1. A report is linked to a known question ID and duplicate submissions of the same normalized comment for that question return the existing report.
2. Faculty can process a report in replay or explicitly configured live mode. Replay is clearly labelled and must not be mistaken for a live AI response.
3. Faculty inspect the verdict, confidence, evidence, deterministic checks, proposed edit and student-reply preview.
4. Approve or reject persists the review and an audit record. Neither action updates the question data or sends a reply.
5. Any model failure is visible and routes through a conservative fallback; it does not switch to replay.

The existing sample queue contains 44 historical reports on 39 reported questions and 18 unreported findings. The checked-in route counts (19 auto-apply eligible, 8 faculty review, 17 no change) are original offline replay results, not production actions or a verified accuracy study.

## Safety model

The LLM only proposes structured changes. Python remains authoritative for:

- Closed verdict/repair taxonomy and field-level permissions.
- Exact unique edit anchors and repair-specific integrity invariants.
- Question-type and answer-key validation against the stored record and blind solve.
- Minimum confidence, with stricter thresholds for answer-key/type changes.
- Prompt-injection screening and blocking of auto-apply on injected reports.
- Auto-apply eligibility; missing option content that cannot be derived is never invented.
- Student reply consistency with the final route.

The blind solver sees only the question stem/options, never the stored key, stored solution, or student complaint. Unreported sweep findings are presented for review. Approval in the new API is not the same as production publication.

## Metrics and interpretation

Operational rates (report volume, faculty-review rate, no-change rate, auto-apply eligibility, token usage, API failures, latency, and configured-price cost estimates) describe a run. Cost is unknown unless current account pricing is explicitly configured.

Quality metrics require independently verified labels:

- **Classification accuracy:** correct report verdicts / labeled reports.
- **Answer-key accuracy:** correct proposed answer changes / labeled answer-key cases.
- **Repair correctness:** correct proposed repair/edit / labeled repairs.
- **False-positive / false-negative rate:** defect classifications against verified defect labels.
- **Auto-apply precision:** correct auto-apply eligible decisions / labeled auto-apply decisions.

The Claude replay is a model-agreement baseline, not a ground-truth set. This repository does not currently contain independent labels for all reports, so accuracy/precision metrics must remain unavailable until such labels are collected. Do not present agreement as correctness.

## What should never auto-apply

1. New authored content (a missing distractor, replacement figure, or rewritten assertion/reason).
2. Answer-key changes without independent support and a passing high-stakes guard.
3. Changes influenced by an injected student comment.
4. Curriculum or syllabus decisions.
5. Defects discovered only by an unreported sweep.

## Success metric and rollout

The primary post-launch safety metric should be **revert rate of published auto-fixes by repair type**, with answer-key changes monitored separately. This metric is not available in the current demo because production publishing and its feedback loop are not implemented.

### Production roadmap

1. Add faculty identity and role-based authorization; the minimal local API has no authentication and must not be exposed publicly.
2. Connect to a governed question-bank staging system with version checks, explicit publish/rollback, and no direct model writes.
3. Add a transactional outbox for student replies and a separate delivery/audit status.
4. Collect independently labeled evaluation cases and report quality metrics with confidence intervals.
5. Configure monitored timeouts, rate limits, privacy/data retention, backups, alerts, and provider cost controls.
6. Conduct a staged faculty pilot before considering limited auto-publication; keep uncertain and high-risk repairs in review.

## Longer-term idea

Use aggregate student attempt patterns to prioritize potentially broken keys before reports arrive. This should only create review candidates; it must not change a key automatically. Regrading or notifying students would require an independently validated correction and an auditable product workflow.
