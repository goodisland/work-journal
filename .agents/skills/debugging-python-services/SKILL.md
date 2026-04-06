---
name: debugging-python-services
description: Use when debugging Python services running under Docker, supervisor, or systemd. Trigger for logs, tracebacks, restart loops, import errors, dependency issues, health check failures, port binding errors, permission problems, and environment mismatches. Do not use for greenfield feature implementation or frontend-only work.
---

# debugging-python-services

## Purpose
Investigate runtime failures in Python-based services and produce a safe, evidence-based fix plan.

## When to use
- supervisor restart loop
- systemd failure
- docker container exits immediately
- traceback investigation
- missing package or import error
- health check failure
- permission denied
- port already in use
- environment variable mismatch

## Do not use
- new feature design
- UI-only edits
- product planning

## Inputs to collect
1. service name
2. runtime type: docker / supervisor / systemd / plain python
3. latest visible error
4. log path or log command
5. expected healthy behavior

## Workflow
1. Identify the process manager and startup command.
2. Read the latest failing logs first.
3. Classify the failure:
   - import / dependency
   - config / env var
   - file permission
   - network / DNS
   - port conflict
   - resource issue
   - code regression
4. Find the smallest safe fix.
5. Re-run the minimum verification needed.
6. Summarize:
   - root cause
   - evidence
   - exact change
   - remaining risk

## Verification
- service starts cleanly
- no immediate restart loop
- health check passes if applicable
- expected command or endpoint works
- same error no longer appears in the latest logs

## Output format
- Findings
- Root cause
- Evidence
- Fix
- Verification
- Remaining risk

## Safety
- Prefer reversible changes
- Do not delete logs or configs unless explicitly requested
- Preserve config backups before editing
- If evidence is incomplete, state uncertainty clearly