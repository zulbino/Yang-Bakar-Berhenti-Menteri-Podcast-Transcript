"""Refuse a commit that ships rewrite output nobody has read. Wired as .git/hooks/pre-commit.

WHY THIS EXISTS. I broke the same rule twice on 2026-09-13, in the same way both times.
The rule, from every handoff this repo has written: *"The rewrites run one at a time from
data/_queue_rewrites.sh ... and they COMMIT NOTHING. Read each log's verdict line, check
the four checkers for that episode, then commit."*

What went wrong: I staged with `git add -A` while a rewrite queue was still writing. Three
regenerations went into a commit whose message was about something else, without their
verdicts being read and without the four post-steps. It was not harmless.
`normalize_speaker_labels.py` then found four files carrying `**Rafizi Ramli:**` labels,
which the rewrite stage reintroduces on every single run, against the short-name
convention. Those would have shipped.

So this is the mechanical version of a rule that was already written down twice and
followed neither time. Two checks, both narrow:

  QUEUE LIVE       A data/_*queue*.out log exists whose last line has no `finished:`
                   marker, AND interview*.md files are staged. That is the exact shape of
                   the mistake: committing mid-queue. Waiting is free; the queue prints
                   `finished:` when it is done.
  VERDICT UNREAD   An episode's interview*.md is staged and its data/_<tag>_gate_rewrite.out
                   holds neither `KEPT candidate` nor `RESTORED incumbent`. Either the run
                   never finished or it is not the run that produced these files.

WHAT IT DOES NOT DO. It does not check the four post-steps, because running them leaves no
durable marker and a false refusal is worse than a missed one. It does not look at
processes: the standing rule in this repo is to chain on log contents, never on a process
check. And it never blocks a commit with no interview files staged, so script, data and
documentation commits are untouched.

`--force` prints the findings and exits 0, for the case where someone has read the logs and
knows why. `git commit --no-verify` also bypasses it, which is deliberate: a guard that
cannot be overridden gets deleted instead of used.

  python scripts/guard_commit.py            # what the hook runs
  python scripts/guard_commit.py --force    # report, do not block
"""
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERDICT = re.compile(r"KEPT candidate|RESTORED incumbent")
# Older queues in this repo signed off as `rewrite queue done` and `adoption queue done`,
# before `finished:` became the convention the waiters grep for. Accept all of them, or
# every finished queue from a past session reads as live.
FINISHED = re.compile(r"finished:|queue done|\bdone\b\s*$", re.M)
# And a log nobody has written to in an hour is not a running queue whatever it says. This
# is the recency half of the test: without it, one truncated log from a killed job would
# block every commit forever.
LIVE_WINDOW = 3600


def staged():
    out = subprocess.run(["git", "diff", "--cached", "--name-only"],
                         cwd=ROOT, capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l.strip()]


def tags_of(paths):
    """Episode tags whose interview files are staged."""
    tags = set()
    for p in paths:
        if "/interview" not in p.replace("\\", "/"):
            continue
        m = re.search(r"/\d{4}-\d{2}-\d{2}-(ep\d+)-", p.replace("\\", "/"))
        if m:
            tags.add(m.group(1))
    return sorted(tags)


def main():
    force = "--force" in sys.argv
    tags = tags_of(staged())
    if not tags:
        return 0

    problems = []
    for log in sorted((ROOT / "data").glob("_*queue*.out")):
        text = log.read_text(encoding="utf-8", errors="replace").strip()
        stale = time.time() - log.stat().st_mtime > LIVE_WINDOW
        if text and not stale and not FINISHED.search(text):
            problems.append(
                f"{log.name} has not printed `finished:` -- a rewrite queue is still "
                f"running. Its last line: {text.splitlines()[-1][:70]!r}. Wait for it, "
                f"then read each verdict.")

    for tag in tags:
        log = ROOT / "data" / f"_{tag}_gate_rewrite.out"
        if not log.exists():
            continue
        if not VERDICT.search(log.read_text(encoding="utf-8", errors="replace")):
            problems.append(
                f"{tag}: interview files are staged but {log.name} shows no verdict "
                f"(`KEPT candidate` or `RESTORED incumbent`). Read the log first.")

    if not problems:
        return 0

    where = "WARNING (--force)" if force else "REFUSING THIS COMMIT"
    print(f"{where}: staged interview files for {', '.join(tags)}\n"
          + "\n".join(f"  - {p}" for p in problems)
          + "\n\nThe rule: read each gate log's verdict, run the four post-steps it names "
            "(rebuild_roster.py --write, normalize_speaker_labels.py --write, "
            "build_episode_index.py, qa_check.py), run the checkers, THEN commit.\n"
            "Stage the episodes deliberately instead of `git add -A`. "
            "Override with --no-verify only if you have read the logs.",
          file=sys.stderr)
    return 0 if force else 1


if __name__ == "__main__":
    sys.exit(main())
