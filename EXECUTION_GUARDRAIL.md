# Digital Edge Lab — Sustained Execution Guardrail

## Trigger commands
- `DEL-ALL`: Activate all execution modes below together.
- `DEL-EXECUTE`: Execute the full outstanding roadmap in the active chat session.
- `DEL-RESUME`: Reconstruct the verified state and continue from the next unfinished task.
- `DEL-OVERDUE`: Prioritize overdue requirements; don't defer them to easier tasks.
- `DEL-UNBLOCK`: Investigate blockers and implement reasonable alternatives/workarounds.
- `DEL-REPEAT`: Iterate fix → test → inspect → fix → retest until a quality gate passes or a real external blocker is reached.
- `DEL-CHECK`: Inspect repository, branch/PR state, latest Actions, tests, and deliverables.
- `DEL-VERIFY`: Verify implementation and outputs with evidence, not assumptions.
- `DEL-COMMIT`: Commit complete, validated changes.
- `DEL-TRACK`: Keep the roadmap and work ledger accurate, separating done, in progress, blocked, and unverified.
- `DEL-FINAL`: Run the full acceptance audit; do not claim readiness without evidence.

## Execution rules
1. Commands authorize sustained execution in the currently open conversation/session. Do not end the session after a single small edit or test just to send a progress message. A lack of incoming user messages is not an interruption.
2. Work across all unfinished requirements, not only the easiest or most recently touched task.
3. Maintain a loop: inspect → prioritize → implement → run checks → examine actual results → fix → rerun → commit → proceed to the next outstanding task.
4. A failed workflow/test/render is a diagnosis-and-repair task. Review its detailed logs and artifacts; do not report failure and stop while reasonable fixes remain.
5. Never use progress reporting as a substitute for code changes, verification, or the next roadmap task.
6. Track actual elapsed time when measurable. Do not fabricate time spent or claim a background process ran after the response.
7. Workarounds must preserve the project requirements (free/open-source, zero budget, no TinyFish, no paid API/services/GPU rentals without owner approval, genuine animated 3D—not slideshow or camera-only tricks).
8. Keep independent tasks moving even when one task is blocked. A blocker only pauses the blocked portion, not the rest of the roadmap.
9. Completion is evidence-gated: identify actual test results, verified rendered media/artifacts, QA reports, source/licensing and any human-review requirements. Workflow success alone is not proof of video quality or production readiness.
10. When a session must end, report concrete commits, checks/results, remaining tasks and exact external blockers. Never present partial work as finished.

## DEL-ALL combined mode
`DEL-ALL` means `DEL-EXECUTE + DEL-RESUME + DEL-OVERDUE + DEL-UNBLOCK + DEL-REPEAT + DEL-CHECK + DEL-VERIFY + DEL-COMMIT + DEL-TRACK + DEL-FINAL`. It is the strongest sustained-execution directive; it must not be reduced to a status report or one isolated fix.
