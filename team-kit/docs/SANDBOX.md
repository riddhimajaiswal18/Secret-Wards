# The sandbox: what a submission can and cannot do

Every team's code is untrusted. It runs on the organiser's machine, next to the hidden
truth, the attacker's knowledge, the master seed and every other team's work. The sandbox
makes sure none of that is reachable, and that every team gets the same resources.

## Isolation levels

`raksha-eval` detects the strongest level the machine supports and records it on every
run record and scorecard (`network_isolation`).

| Level | How | What it guarantees |
|---|---|---|
| **full** (required for official runs: `--require-isolation`) | unprivileged `unshare --user --net --mount --pid --fork --mount-proc` | no network; truth, attacker data, seeds, the sealed evaluator code, the organiser's home directory and other teams' folders are hidden behind empty tmpfs mounts; the submission sees only its own processes |
| netns | `unshare --user --net` | no network only (flagged on the scorecard) |
| none | plain process | nothing (flagged; never use for official scoring) |

The **full** level needs unprivileged user namespaces (the default on most Linux
distributions; on Ubuntu 24.04+ AppArmor may need
`sysctl kernel.apparmor_restrict_unprivileged_userns=0`).

## What is hidden during `run`

| Path | Why |
|---|---|
| `<dataset>/truth/`, `<dataset>/attacker/`, the whole original dataset folder | the answers and the attacker's knowledge |
| the evaluator repository (incl. `seeds/`) | the generator, the chaos catalogue and the master seed |
| the organiser's `$HOME` | GitHub tokens, SSH keys, browser data |
| other teams' repositories and runs | copying another team's output |
| host processes (`/proc`) | the evaluator's command line (which contains the seed) |

The submission still sees: its own repository (with its `.venv`), a read-only copy of
the input, an empty output folder, and private `TMPDIR` and `HOME` folders. Those
private folders are scanned for PII after the run.

A unit test (`tests/test_runner.py::CheatingTests`) runs a malicious "submission" that
tries to read the truth file, the organiser's `.ssh` and `.config`, and list host
processes. All of it fails.

## What happens during `setup`

`setup` needs the network (to `pip install`), so it runs **with** network but **with the
same masks**. A malicious setup script cannot read tokens or keys to exfiltrate them.
Before `setup`, the evaluator creates a private `.venv` in the repository, so `pip install`
never touches the system or another team. Every team shares a read-mostly pip download
cache, which makes 300 installs fast.

If a team has no `setup` command but ships `requirements.txt`, the evaluator runs
`pip install -r requirements.txt` for it.

## Equal resources

* **CPU:** each parallel slot owns a disjoint set of cores (CPU affinity). The team's
  runs **and** its scoring are pinned there, so a heavy neighbour cannot slow anyone
  down.
* **Memory:** a 50 ms watchdog sums the RSS of the whole process tree and kills it above
  the limit (`memory_exceeded`).
* **Time:** a hard wall-clock limit per run (`timeout`).
* **Files:** core dumps are off; a single file may not exceed 2 GB.

## Evidence the sandbox records

Every `run.json` contains the status, exit code, wall and CPU time, peak RSS, the
isolation level, the SHA-256 of the input the run received (scoring refuses a run from
a different dataset), whether the input was modified, temp-file leftovers, and
**suspected network attempts**: stdout/stderr are searched for resolver and connection
errors (`Temporary failure in name resolution`, `Network is unreachable`,
`Max retries exceeded`…). A hit puts a NETWORK ATTEMPT flag on the scorecard for the
judges. The attempt itself always fails, because there is no network.
