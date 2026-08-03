# Parallel frontier

Use parallel workers only when all isolation gates pass:

1. Every selected ticket is simultaneously on the live frontier.
2. Their anticipated write scopes and external test environments are disjoint.
3. Each worker has an isolated git worktree and ticket branch created from the
   same integration commit.
4. Enough worker slots remain for the coordinator to stay active.

Claim every selected ticket before dispatch. Give each worker only its own
worktree, branch, ticket, parent spec, and implementation contract. Workers
leave tracker settlement to the coordinator.

Integrate returned commits one at a time in deterministic frontier order. After
each integration, verify that ticket against the updated integration branch and
settle it before integrating the next. A merge conflict, overlapping semantic
change, or shared-environment test converts the affected work to sequential
execution.

Serialize GUI automation, hosted-Mac validation, deployment, migration, and
live external-effect tests even when code implementation ran in parallel.

Parallel execution is complete only when every dispatched worker has returned,
each accepted commit is integrated and settled, and every rejected or blocked
result has tracker evidence.
