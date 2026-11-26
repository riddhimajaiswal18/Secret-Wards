#!/usr/bin/env python3
"""Secret Wards pre-submit check (standard library only).

Checks YOUR REPOSITORY the way the organisers will run it:

    python3 check_submission.py --repo ../my-team-repo           # quick: files and raksha.toml
    python3 check_submission.py --repo ../my-team-repo --run     # also runs your system 3 times

With --run it runs your `run` command on the practice data (like event day, but with
your own Python and WITH internet, so also test offline yourself), then checks:
the output contract, identical output on a repeat run, different output with a
different secret, and that RAKSHA_SECRET was never written anywhere.

Run your `setup` command yourself first (for example `pip install -r requirements.txt`).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BANNED = re.compile(r"^\s*(openai|anthropic|google-generativeai|google-genai|ollama|llama[-_]cpp|llama-index|"
                    r"langchain\S*|vllm|mistralai|cohere|groq|together|litellm|gpt4all|ctransformers)\b", re.I | re.M)

ok_count = fail_count = warn_count = 0


def ok(msg):
    global ok_count
    ok_count += 1
    print(f"  ✅ {msg}")


def fail(msg):
    global fail_count
    fail_count += 1
    print(f"  ❌ {msg}")


def warn(msg):
    global warn_count
    warn_count += 1
    print(f"  ⚠️  {msg}")


def read_toml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        import tomllib
        return tomllib.loads(text)
    except ModuleNotFoundError:  # Python 3.10: tiny fallback for the [submission] table
        sub, section = {}, None
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("["):
                section = line.strip("[]").strip()
            elif "=" in line and section == "submission":
                k, v = line.split("=", 1)
                v = v.split(" #", 1)[0].strip()
                sub[k.strip()] = v.strip('"').strip("'")
        return {"submission": sub}


def tree_digest(out: Path) -> str:
    h = hashlib.sha256()
    for name in ("sanitized", "records.jsonl"):
        p = out / name
        items = sorted(p.rglob("*")) if p.is_dir() else ([p] if p.exists() else [])
        for f in items:
            if f.is_file():
                h.update(f.relative_to(out).as_posix().encode() + b"\0" + f.read_bytes() + b"\0")
    return h.hexdigest()


def run_once(cmd_t: str, repo: Path, inp: Path, out: Path, secret: str, timeout: int):
    cmd = cmd_t.replace("{input}", shlex.quote(str(inp))).replace("{output}", shlex.quote(str(out)))
    env = dict(os.environ, RAKSHA_SECRET=secret, RAKSHA_INPUT=str(inp), RAKSHA_OUTPUT=str(out),
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    venv = repo / ".venv" / "bin"
    if venv.is_dir():
        env["PATH"] = f"{venv}{os.pathsep}{env.get('PATH', '')}"
    t0 = time.monotonic()
    try:
        p = subprocess.run(cmd, shell=True, cwd=repo, env=env, capture_output=True, timeout=timeout)
        return p.returncode, time.monotonic() - t0, p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return None, time.monotonic() - t0, b""


def main() -> int:
    ap = argparse.ArgumentParser(description="Secret Wards pre-submit check")
    ap.add_argument("--repo", default=".", help="your submission repository (default: current folder)")
    ap.add_argument("--input", default=str(HERE / "dev" / "input"), help="input data (default: the practice data)")
    ap.add_argument("--run", action="store_true", help="also run your system 3 times and check the output")
    ap.add_argument("--timeout", type=int, default=900, help="seconds per run (event limit: 15 minutes)")
    a = ap.parse_args()
    repo, inp = Path(a.repo).resolve(), Path(a.input).resolve()

    print(f"\nSecret Wards pre-submit check: {repo}\n")
    print("1) Repository files")
    sub = {}
    toml = repo / "raksha.toml"
    if not toml.is_file():
        fail("raksha.toml is missing at the ROOT of the repository (a sub-folder does not count)")
    else:
        try:
            sub = read_toml(toml).get("submission") or {}
        except Exception as exc:  # noqa: BLE001
            fail(f"raksha.toml cannot be parsed: {exc}")
        if sub:
            ok("raksha.toml found at the root")
            name = str(sub.get("name", "")).strip()
            if not name or name == "your-team-name":
                fail('set [submission] name to your real team name (not "your-team-name")')
            else:
                ok(f"team name: {name}")
            run = str(sub.get("run", ""))
            if not run:
                fail("[submission] run is missing")
            elif "{input}" not in run or "{output}" not in run:
                fail("run must contain both {input} and {output}")
            else:
                ok(f"run: {run}")
            if sub.get("setup"):
                ok(f"setup: {sub['setup']}")
        elif toml.is_file():
            fail("raksha.toml has no [submission] table")

    if (repo / "README.md").is_file():
        size = len((repo / "README.md").read_text(encoding="utf-8", errors="ignore").split())
        (ok if size >= 300 else warn)(f"README.md found ({size} words)"
                                      + ("" if size >= 300 else ": judges expect setup, architecture, "
                                         "how each part works, security design, limitations"))
    else:
        fail("README.md is missing")

    pdfs = [p for p in repo.rglob("*.pdf") if ".git" not in p.parts and ".venv" not in p.parts
            and "dev" not in p.relative_to(repo).parts[:1]]
    if pdfs:
        ok(f"Project Brief PDF found: {pdfs[0].relative_to(repo)}")
    else:
        warn("no PDF in the repo: you must ALSO submit the 2-page Project Brief PDF (see docs/PROJECT_BRIEF.md)")

    req = repo / "requirements.txt"
    if "requirements.txt" in str(sub.get("setup", "")) and not req.is_file():
        fail("setup installs requirements.txt but the file is missing")
    if req.is_file():
        bad = BANNED.findall(req.read_text(encoding="utf-8", errors="ignore"))
        if bad:
            fail(f"requirements.txt lists LLM / hosted-AI packages (not allowed): {', '.join(sorted(set(bad)))}")
        else:
            ok("requirements.txt has no LLM / hosted-AI packages")
    if (repo / "config" / "policy.yaml").is_file():
        ok("config/policy.yaml found")
    else:
        warn("config/policy.yaml not found (recommended: your privacy rules)")

    big = [p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts and ".venv" not in p.parts
           and p.stat().st_size > 100 * 1024 * 1024]
    if big:
        warn(f"files over 100 MB (GitHub rejects them; models over 50M parameters are not allowed): "
             f"{', '.join(str(p.relative_to(repo)) for p in big[:3])}")

    if a.run and sub.get("run") and "{input}" in str(sub["run"]):
        print("\n2) Running your system on the practice data (3 runs)")
        if not inp.is_dir():
            fail(f"input folder not found: {inp}")
        else:
            work = Path(tempfile.mkdtemp(prefix="sw-check-"))
            secret_a, secret_b = "check-secret-" + os.urandom(6).hex(), "check-other-" + os.urandom(6).hex()
            before = tree_digest_input(inp)
            outs = {}
            for tag, secret in (("A", secret_a), ("B", secret_a), ("C", secret_b)):
                out = work / f"out_{tag}"
                out.mkdir()
                code, secs, logs = run_once(str(sub["run"]), repo, inp, out, secret, a.timeout)
                outs[tag] = (out, code, secs, logs, secret)
                if code is None:
                    fail(f"run {tag} hit the {a.timeout}s time limit")
                    break
            out_a, code_a, secs_a, logs_a, _ = outs["A"]
            if code_a == 0:
                ok(f"exit code 0 in {secs_a:.1f}s")
            elif code_a is not None:
                fail(f"exit code {code_a}. Last output:\n      "
                     + logs_a.decode('utf-8', 'replace').strip()[-600:].replace("\n", "\n      "))
            v = subprocess.run([sys.executable, str(HERE / "validate_output.py"), "--input", str(inp),
                                "--output", str(out_a)], capture_output=True, text=True)
            if "CONTRACT OK" in v.stdout:
                ok("output contract: CONTRACT OK")
            else:
                fail("output contract problems:\n      " + v.stdout.strip().replace("\n", "\n      "))
            if code_a != 0:
                print("      (repeat-run checks skipped until run A succeeds)")
            if code_a == 0 and "B" in outs and outs["B"][1] is not None:
                (ok if tree_digest(out_a) == tree_digest(outs["B"][0]) else fail)(
                    "same secret twice → identical sanitized/ and records.jsonl"
                    if tree_digest(out_a) == tree_digest(outs["B"][0])
                    else "same secret twice gave DIFFERENT output (sort your files, avoid random/time/set order)")
            if code_a == 0 and "C" in outs and outs["C"][1] is not None:
                if tree_digest(out_a) != tree_digest(outs["C"][0]):
                    ok("different secret → different output (pseudonyms / date shifts are keyed)")
                else:
                    warn("a different RAKSHA_SECRET gave identical output: key your pseudonyms and date shifts "
                         "with RAKSHA_SECRET")
            leaked = []
            for tag, (out, _, _, logs, secret) in outs.items():
                if secret.encode() in logs:
                    leaked.append(f"run {tag} stdout/stderr")
                for f in out.rglob("*"):
                    if f.is_file() and secret.encode() in f.read_bytes():
                        leaked.append(str(f.relative_to(out)))
            (fail if leaked else ok)(f"RAKSHA_SECRET written to: {', '.join(leaked[:5])}" if leaked
                                     else "RAKSHA_SECRET is never written to output or logs")
            (ok if tree_digest_input(inp) == before else fail)(
                "input folder left unchanged" if tree_digest_input(inp) == before
                else "your system MODIFIED the input folder (penalised)")
            shutil.rmtree(work, ignore_errors=True)
            print("\n   Next: python3 check_dev.py --output <your output>  shows how GOOD the output is.")
            print("   Event day has NO internet: also test with your network switched off.")
    elif not a.run:
        print("\n   Tip: add --run to also run your system and check its output.")

    print()
    if fail_count:
        print(f"FIX THE ❌ ITEMS ({fail_count}), then run this again.")
        return 1
    print("READY TO SUBMIT" + (f" (check the {warn_count} ⚠️ notes)" if warn_count else ""))
    print("Submit: your GitHub repo link + your 2-page Project Brief PDF, before the deadline.")
    return 0


def tree_digest_input(inp: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(inp.rglob("*")):
        if f.is_file():
            h.update(f.relative_to(inp).as_posix().encode() + b"\0" + f.read_bytes())
    return h.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
