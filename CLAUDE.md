# ghambla — working agreement

## Delegate production code. Always.

**Any task that produces a meaningful volume of code or text goes to the
DeepSeek harness, not to Claude.** This is not a suggestion to weigh up per
task — it is the default, and using Claude instead needs a stated reason.

```bash
python3 ~/tools/delegate/delegate.py -f spec.md \
    -c <context files> --extract -o <target> \
    --verify ".venv/bin/pytest -q" --retries 2
```

Repo: `git@github.com:baeley-canning/DeepSeek-Harness-.git`

**Delegate:** new modules, new functions, refactors, call-site fallout, CLI
wiring, boilerplate, mechanical edits across many files, config, docs, README
sections. Anything where the spec is short and the output is long.

**Do not delegate:** the tests. Measured, not assumed — a delegate's own tests
for the volatility signal survived all five mutations thrown at them while
verifying nothing. If the delegate writes both the code and its check, nothing
catches the delegate. Claude writes the tests, the delegate writes the code,
the tests are the gate.

**Before writing anything by hand, ask: could this have been a spec?** If yes,
write the spec instead. Hand-written inline `python3 - <<PY` patches to rewrite
source files are the most common leak — those are delegation work.

Use `--review` for a cold second opinion. It is a filter, not a gate: it has
passed files the tests then failed, and it once caught a dead `max_daily_loss`
limit the tests missed. Treat it as neither authoritative nor useless.

## Report outcomes, not process

Cassius is the customer. Fix it, verify it, state the result in a line or two.
No narration of bugs found and fixed along the way — that is the contractor's
job to absorb. Decide rather than presenting options.

The one exception is anything that changes what he is actually getting: money
at risk, a number that would mislead, a promise that cannot be kept. Those get
said once, briefly.

## Verify before claiming

Run the command, read the output, then state the result. "Tests pass" without
a run is a lie with good intentions. Never commit before running the suite —
that has already shipped a broken schema here.

## This project's rules

- **Point-in-time or nothing.** Every read goes through `bars_as_of` /
  `news_as_of`. A lookahead bug is the one failure that makes every number
  fiction.
- **One decision path.** Any logic in the backtest but not the live cycle, or
  vice versa, is a bug. Four such divergences have already shipped:
  the scorer, the risk gate, the cash buffer, the regime filter.
  `tests/test_live_parity.py` exists to catch the fifth.
- **Pre-register before evaluating.** Gate 0 results are committed before the
  run, not after. Seven candidates have failed; an eighth on the same data is
  p-hacking, not research.
- **Never represent an unvalidated strategy as validated.** No strategy has
  passed Gate 0. The dashboard, the journal and the README all say so, and
  must continue to.
- **stdlib only** for runtime. `dependencies = []` is deliberate.

## Conventions

Docstrings lead with a one-line summary, then explain WHY, not WHAT. Match the
surrounding file's comment density. Mutation-test any signal whose sign or
arithmetic carries meaning — `sed` the operator, confirm the suite fails.
