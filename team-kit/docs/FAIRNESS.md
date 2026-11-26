# Fairness protocol: how "no partiality" is enforced

Impartiality is not a promise; it is a set of mechanisms anyone can verify afterwards.

> For teams: the `raksha-eval` commands below are run by the organisers. The evaluator
> repository is published after the results, so anyone can re-run them and check.

## 1. Fix the rules before anyone submits

| Commitment | How |
|---|---|
| Scoring rules | `config/scoring.toml` is published; its SHA-256 appears on every scorecard and on the leaderboard. |
| Evaluator code | The git commit of the evaluator repository is published at the opening ceremony and stamped on the leaderboard. |
| Hidden data | `raksha-eval seed commit` creates a random master seed + nonce and prints `SHA-256("raksha-seed-commit-v1|seed|nonce")`. **Publish that commitment** at the opening ceremony; keep `seeds/secret.json` offline. |
| Submission contract | [SPEC.md](SPEC.md), unchanged during the event. |

After submissions close, reveal the seed and nonce. Anyone can run
`raksha-eval seed verify --seed … --nonce … --commitment …`, regenerate the hidden
datasets with `raksha-eval seed derive` + `generate`, and compare the input hashes printed
on the leaderboard. **No one, organisers included, can choose data after seeing the
submissions.**

## 2. Freeze the submissions at the deadline

```bash
raksha-eval freeze --submissions submissions.csv --out submissions.lock.csv
sha256sum submissions.lock.csv     # publish this hash at the deadline
```

The lockfile records each repository's `HEAD` commit at the deadline. The tournament
checks out exactly that commit; commits pushed later are never evaluated. The
leaderboard records both the frozen and the evaluated commit.

## 3. Identical conditions for every team

* Same hidden datasets, generated once, hash-checked.
* Same sandbox: its own pinned CPUs (for the runs *and* the scoring), a 4 GB process-tree
  memory limit, the same timeout, no network during `run`, fresh read-only inputs, and
  private TMPDIR/HOME. With full isolation the truth, seeds, organiser home and other
  teams are invisible ([SANDBOX.md](SANDBOX.md)). Use `--require-isolation` on the
  official machine, so a run refuses to start without full isolation instead of silently
  running without it.
* Same scoring config, same evaluator commit.
* Run order is shuffled with a seed derived from the master seed (published in
  `tournament.json`). The order cannot matter, but nobody can claim it did.
* Calibration (`raksha-eval calibrate`) **must pass** before any team is scored. If the
  evaluator, config or machine misbehaves, the anchors catch it first.

## 4. Blind judging

`tournament --blind` replaces team names with `Team-XXXX` (hash of the name) in every
leaderboard file. The mapping is written separately to `unblind_key.json`; open it only
after the results are signed off. Scorecards never contain team names.

## 5. Statistics: ties are honest

Teams are evaluated on several hidden datasets (default 3, one of them a **chaos** dataset
measuring generalisation). The leaderboard shows the mean and an interval: a 95% Student-t
interval with three or more datasets, otherwise the observed range. Two neighbouring teams
get different ranks only if the higher one beats the lower one **on every hidden dataset
by more than 1 point** (with five or more datasets, a significant paired t-test also
separates them). Otherwise they share a rank (`=`). Prizes for tied ranks are decided by
the organisers' published tie-break (for example, the privacy category, then the chaos
dataset), not by noise.

## 6. Every number has evidence

Each scorecard lists the leaks (entity type, channel, location), failed probes,
integrity findings, the attack results and the penalties. Because all data is
synthetic, the evidence can be shown to teams after the reveal. Appeals are settled by
re-running the published commit on the revealed seed, which reproduces the same bytes
and the same score.

## 7. What to share with teams, and what to seal

`raksha-eval team-kit --out kit/ --seed <public-dev-seed>` builds exactly what participants
should receive:

| In the team kit (share) | Sealed until results are published |
|---|---|
| PROBLEM_STATEMENT, [SPEC](SPEC.md), [SCORING](SCORING.md), [ATTACKS](ATTACKS.md) | the evaluator repository: the generator, the chaos-round tables, the attacker code |
| a public **dev dataset** with `truth/` and `attacker/` (normal profile) | the master seed (only its commitment is public) and the hidden datasets |
| `scoring.toml` (its hash is the published rule set) | `unblind_key.json` (blind mode) |
| `validate_output.py`, a standalone contract checker that does no scoring | |

Why the code stays sealed during the event: the hidden seed changes every name,
identifier, value and combination, but the **chaos round's catalogue of variation**
(labels, name pool, ID and date formats) lives in the code. Publishing it would let
teams memorise that too. After the results, publish the repository at the committed git
hash so anyone can re-run the evaluation on the revealed seed and get the same bytes and
the same scores.

## 8. Static audit (evidence, not verdicts)

`raksha-eval audit --submission <repo> --dev-dataset <dev>` flags generative-LLM, cloud
and GPU usage, runtime network calls, hard-coded dev identifiers and missing deliverables
(§7 Ground Rules of the statement). Flags go to the judges for review. They never deduct points
automatically, because static analysis has false positives and an automatic penalty
would be a partial judgement.
