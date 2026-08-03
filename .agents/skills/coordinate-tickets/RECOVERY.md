# Recovery

Classify the failed unit before continuing:

- **Worker returned without a commit** — send the same worker one targeted
  follow-up naming the missing completion evidence.
- **A check is red** — preserve the exact failing command and output; send the
  worker a targeted repair. When the failure is reproducible but its cause is
  unclear, require the diagnosing-bugs loop before another fix.
- **Acceptance evidence is missing** — reopen the same worker on the unmet
  criterion; keep the ticket claimed.
- **Integration drift or conflict** — isolate the ticket commit from unrelated
  work, preserve user changes, and resume sequentially from the current
  integration branch.
- **Tracker mutation failed** — keep the verified code commit intact, retry the
  tracker write from live state, and leave the ticket unsettled until both
  surfaces agree.
- **Human gate** — record the decision or permission needed, move the ticket to
  the configured human-ready state, release the claim, and continue any
  independent frontier work.

Allow at most two targeted repair turns after the initial worker result. The
third occurrence of the same failure is a concrete blocker: record its command,
evidence, attempted repairs, and downstream tickets. A different failure starts
its own diagnosis; it does not erase the earlier evidence.

Recovery is complete when the ticket is independently green and can return to
settlement, or when its tracker entry contains enough evidence for a fresh
human or agent to resume without reconstructing the failure.
