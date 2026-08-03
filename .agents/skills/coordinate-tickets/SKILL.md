---
name: coordinate-tickets
description: Coordinate an approved ticket set to completion, blockers-first.
---

# Coordinate Tickets

Drive approved implementation tickets as a **frontier**: claim one unblocked
ticket, dispatch one fresh worker, verify its commit, settle the ticket, and
recompute the frontier. Continue until every ticket is complete or the
remaining work is genuinely blocked.

## Authority

Treat the approved spec and tickets as the authority boundary. This invocation
authorizes their required repository edits, tests, reviews, commits, tracker
claims, and tracker closure. Route these actions to a human gate before acting:

- work outside the approved acceptance criteria;
- new credentials, accounts, permissions, recipients, or secrets;
- destructive or irreversible operations;
- consequential external effects not explicitly pre-authorized by a ticket;
- a product, architecture, or scope decision the artifacts do not settle.

Preserve pre-existing worktree changes as user-owned state. Use repository and
tracker evidence, rather than worker narration, to decide whether work is done.

## 1. Orient

1. Read the repository instructions, `docs/agents/issue-tracker.md`, applicable
   domain docs/ADRs, the parent spec, and every ticket in the approved set.
2. Confirm the user approved the set and that each ticket is agent-ready with
   explicit acceptance criteria and blocking edges.
3. Build the dependency graph from live tracker state. Surface missing tickets,
   cycles, or unresolved planning questions as blockers.
4. Capture the integration branch, baseline commit, worktree status, and all
   pre-existing changes. Start a production branch when the current branch is
   not the intended integration branch.

Orientation is complete only when the exact ticket set, graph, integration
branch, baseline, and ownership of every dirty path are known. If
`docs/agents/issue-tracker.md` is absent, stop for
`/setup-matt-pocock-skills`.

## 2. Claim the frontier

Refresh the tracker immediately before each selection. The **frontier** is every
open, agent-ready, unclaimed ticket whose blockers are complete. Choose the
first ticket in dependency order, using tracker order and then ticket identity
as deterministic tie-breakers.

Claim the ticket as the coordinator's first write:

- GitHub or another real tracker: use its native assignee/claim mechanism.
- Local Markdown: change `Status: ready-for-agent` to `Status: claimed`.

The step is complete when exactly one selected ticket is visibly claimed. If
the frontier is empty, go to the terminal-state check.

## 3. Dispatch one fresh worker

Start an isolated sub-agent or fresh session with only this worker brief:

- the complete ticket body and tracker reference;
- the parent spec and relevant domain/ADR pointers;
- repository path, integration branch, and baseline commit;
- pre-existing paths the worker must preserve;
- instruction to read `.agents/skills/implement/SKILL.md` as the implementation
  contract, including its TDD, test, review, and commit requirements;
- instruction to implement exactly this ticket and leave tracker settlement to
  the coordinator;
- required return evidence: commit hash, acceptance-criterion mapping, test
  commands/results, code-review result and fixes, or a precise blocker.

Wait for that worker; keep coordinator edits out of the worker's write scope.
The step is complete only when the worker returns a ticket commit or concrete
blocker evidence.

When several frontier tickets could materially improve throughput, read
[`PARALLEL.md`](PARALLEL.md) before dispatching more than one worker. Sequential
execution is the default.

## 4. Verify the ticket

Inspect the repository directly:

1. Resolve the returned commit and review its complete diff from the recorded
   baseline.
2. Map every acceptance criterion to observable evidence.
3. Confirm the implementation contract's focused checks, full-suite check, and
   two-axis review completed; rerun checks needed to trust the integration
   branch.
4. Confirm the commit contains one ticket's scope and preserves the known
   pre-existing changes.

The ticket is verified only when every acceptance criterion has evidence, all
required checks pass, review findings are resolved or explicitly accepted by
the spec, and the commit is independently green. For a failed worker, test,
integration, or tracker update, follow [`RECOVERY.md`](RECOVERY.md) before
classifying the ticket.

## 5. Settle and repeat

For a verified ticket, post the commit and concise verification evidence, then
close/resolve it using the configured tracker. For a genuinely blocked ticket,
record the exact blocker and reproduction evidence, move it to the configured
human-ready state, and release its claim.

Refresh the graph after every settlement. Continue with any independent ticket
still on the frontier; a blocked ticket stops only its downstream dependents.

## Terminal state

Finish in exactly one state:

- **complete** — every approved ticket is resolved and the integration branch
  is green;
- **blocked** — open tickets remain, but the live frontier is empty because of
  recorded blockers or human gates;
- **stopped** — the user's explicit time, cost, or stop boundary was reached.

Report completed tickets with commit hashes, checks run, blocked tickets with
their evidence, the remaining frontier, and final branch/worktree state. The
coordination run is not complete while a worker is running, a verified commit
is unsettled, or an unblocked approved ticket remains.
