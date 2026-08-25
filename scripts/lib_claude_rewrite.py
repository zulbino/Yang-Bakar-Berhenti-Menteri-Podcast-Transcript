"""Claude-based rewrite/translate/metadata fallback for the rewrite stage, used
when the Gemini API is unavailable (e.g. billing blocked). Mirrors lib_gemini.py's
rewrite_clean/translate/extract_metadata; the prompt templates and chunking logic
are imported from there since that text is provider-agnostic, not Gemini-specific.

Shells out to the `claude` CLI in headless mode (`claude -p`) rather than calling
the Anthropic API directly -- this environment authenticates through an
enterprise-managed Claude Code login with no standalone Anthropic API key
available, and the CLI reuses that same auth with no extra setup.

Every call passes --system-prompt and a full --disallowedTools list. Without
them, Claude Code's default system prompt (identity, tool schemas, CLAUDE.md,
environment info) gets cached fresh on every one-off CLI invocation --
measured at ~21k cache-creation tokens and $0.08 per call on a trivial
request. Overriding the system prompt and disallowing every tool (these are
pure text-generation calls with no file/bash/agent need) cuts that to ~500
tokens and $0.0016 -- a ~48x reduction with no effect on output quality.
"""
import json
import re
import subprocess

from common import retry
from lib_gemini import (
    CLEAN_PROMPT_TEMPLATE,
    META_PROMPT_TEMPLATE,
    META_SCHEMA,
    TRANSLATE_PROMPT_TEMPLATE,
    _split_into_chunks,
)

MODEL = "claude-sonnet-5"
CLAUDE_EXE = "claude"
# subprocess.run has no default timeout -- confirmed directly: the CLI subprocess
# hung twice in a row on the same episode with near-zero CPU (waiting on something
# that never returned), blocking the pipeline indefinitely with no way to detect
# or recover. A generous but bounded timeout turns that into a normal retry()able
# failure instead.
CLI_TIMEOUT_SECONDS = 600

SYSTEM_PROMPT = "Respond only with the requested output. Do not narrate, explain, or add commentary."

DISALLOWED_TOOLS = ",".join([
    "Agent", "Bash", "Edit", "Glob", "Grep", "PowerShell", "Read", "Write",
    "NotebookEdit", "WebFetch", "WebSearch", "Skill", "Workflow",
    "ScheduleWakeup", "ReportFindings", "AskUserQuestion", "ListAgents",
    "ToolSearch", "CronCreate", "CronDelete", "CronList", "DesignSync",
    "EnterWorktree", "ExitWorktree", "Monitor", "PushNotification",
    "SendMessage", "TaskOutput", "TaskStop", "TodoWrite",
])

CONTINUE_PROMPT = (
    "Continue exactly from where you left off. Do not repeat any earlier "
    "lines, and do not add commentary or a preamble."
)


def get_client():
    return None  # no client object needed -- each call is a fresh CLI invocation


def current_model():
    return MODEL


def _run_claude(prompt, session_id=None, json_schema=None):
    cmd = [
        CLAUDE_EXE, "-p", "--output-format", "json", "--model", MODEL,
        "--safe-mode", "--disallowedTools", DISALLOWED_TOOLS, "--effort", "low",
    ]
    if session_id:
        cmd += ["--resume", session_id]
    else:
        cmd += ["--system-prompt", SYSTEM_PROMPT]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]

    try:
        proc = subprocess.run(cmd, input=prompt.encode("utf-8"), capture_output=True, timeout=CLI_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"claude CLI hung past {CLI_TIMEOUT_SECONDS}s, no response")
    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI exited {proc.returncode}: {proc.stderr.decode('utf-8', errors='replace')}")

    events = json.loads(proc.stdout.decode("utf-8"))
    result = next(e for e in events if e.get("type") == "result")
    if result.get("is_error"):
        raise RuntimeError(f"claude CLI error ({result.get('subtype')}): {result.get('result')}")
    return result


def _generate_with_continuation(prompt):
    # A single turn can hit max_tokens before a long chunk's rewrite/
    # translation is complete; keep asking the model to continue in the same
    # (--resume'd) session until it finishes naturally, capped to avoid a
    # runaway loop. Resuming keeps the prior turn cached (cheap), unlike
    # starting a fresh CLI invocation per continuation round.
    result = _run_claude(prompt)
    full_text = result["result"]
    session_id = result["session_id"]
    for _ in range(8):
        if result.get("stop_reason") != "max_tokens":
            return full_text
        result = _run_claude(CONTINUE_PROMPT, session_id=session_id)
        full_text += result["result"]
    raise RuntimeError(f"{MODEL} still hitting max_tokens after 8 continuations")


# A chunk can finish cleanly (stop_reason=STOP, not max_tokens -- so
# _generate_with_continuation never kicks in) after the model chose to condense
# or summarize that chunk instead of fully rewriting it -- the same failure
# class lib_gemini.py's CHUNK_CHARS comment describes, just not prevented by
# chunking alone. retry() only catches exceptions, so an under-rewritten chunk
# sails through undetected, silently deflating the whole file's rewrite ratio.
# Confirmed directly (ep45, ep49): both improved sharply after a rewrite retry
# elsewhere but stayed well under qa_check.py's 0.35 file-level threshold,
# with the missing content concentrated at the very end -- consistent with one
# late chunk getting condensed rather than every chunk failing equally.
#
# Root-caused directly on ep45's worst chunk (its opening ~20 minutes of
# heavily disfluent political banter): not a chunk-size or prompt-wording
# problem, and not extended-thinking eating the output budget either
# (disabling thinking barely moved the ratio: 0.46 -> 0.49 in isolated
# tests). The model has a persistent tendency to compress heavily disfluent,
# filler-and-reaction-heavy banter (short interjections, "kan"/"lah"/"hmm",
# one-word reactions) well below a full rewrite for this specific content,
# regardless of instructions telling it not to. Confirmed NOT fully
# deterministic either: across 9 total sampled attempts on this one chunk
# (2 different exact chunk-boundary versions), ratios ranged from 0.13 to
# 0.51 depending on chunk size, reasoning effort, and plain sampling
# variance, clustering tightly *within* a given attempt run (5 consecutive
# attempts within one run landed 0.127-0.136) but shifting notably *between*
# separate CLI invocations of the identical prompt+chunk. A smaller chunk
# (~39.8k -> ~19.7k chars) and --effort low are kept since they measurably
# helped in isolated single-sample tests, but retries alone could not
# reliably force this specific content above roughly 0.3, let alone the
# ~1:1 ratio full, working rewrites land at on less disfluent content
# (confirmed: ep30/ep37 redos landed at ratio 0.96). MIN_CHUNK_RATIO is set
# low enough to stop retrying past the point where retries stop helping
# (a floor near the observed worst-case ~0.13, not the ideal), so a chunk
# that's merely heavily-compressed-but-real passes instead of burning all
# 10 attempts for a near-certain failure -- only a near-empty or clearly
# broken result should still fail this check. The output file's overall
# ratio can still legitimately land below qa_check.py's 0.35 threshold for
# an episode with a segment like this; that's qa_check.py correctly
# surfacing it for a human look, not a bug to silence. See ARCHITECTURE.md
# for the full investigation.
CLAUDE_CHUNK_CHARS = 20_000
MIN_CHUNK_RATIO = 0.10


def rewrite_clean(client, raw_text):
    chunks = _split_into_chunks(raw_text, CLAUDE_CHUNK_CHARS)

    results = []
    for chunk in chunks:
        prompt = CLEAN_PROMPT_TEMPLATE.format(raw_text=chunk)

        def call(prompt=prompt, chunk=chunk):
            result = _generate_with_continuation(prompt)
            if len(result) < len(chunk) * MIN_CHUNK_RATIO:
                raise RuntimeError(
                    f"clean rewrite came back {len(result)} chars for a {len(chunk)}-char "
                    "chunk -- suspected condensation instead of a full rewrite"
                )
            return result

        results.append(retry(call, max_attempts=10, base_delay=30, what="clean rewrite"))
    return "\n\n".join(results)


def translate(client, mixed_text, target_language):
    chunks = _split_into_chunks(mixed_text, CLAUDE_CHUNK_CHARS)

    results = []
    for chunk in chunks:
        prompt = TRANSLATE_PROMPT_TEMPLATE.format(target_language=target_language, mixed_text=chunk)

        def call(prompt=prompt, chunk=chunk):
            result = _generate_with_continuation(prompt)
            if len(result) < len(chunk) * MIN_CHUNK_RATIO:
                raise RuntimeError(
                    f"translation came back {len(result)} chars for a {len(chunk)}-char "
                    "chunk -- suspected condensation instead of a full rewrite"
                )
            return result

        results.append(retry(call, max_attempts=10, base_delay=30, what=f"translate to {target_language}"))
    return "\n\n".join(results)


def _looks_like_placeholder(meta):
    # Confirmed real failure mode (ep13, ep47): the CLI's --json-schema
    # enforcement occasionally returns a schema-conformant but generic stub
    # ("Topic A"/"Topic one", "Test summary.") instead of real extracted
    # content, on long unchunked metadata calls specifically. retry() only
    # catches exceptions, so this sailed through undetected until now.
    if re.match(r"(?i)^test summary\.?$", meta.get("summary", "").strip()):
        return True
    if any(re.match(r"(?i)^topic [a-z0-9]+$", t.strip()) for t in meta.get("topics", [])):
        return True
    return False


def extract_metadata(client, clean_text):
    prompt = META_PROMPT_TEMPLATE.format(clean_text=clean_text)
    schema = {**META_SCHEMA, "additionalProperties": False}

    def call():
        result = _run_claude(prompt, json_schema=schema)
        meta = json.loads(result["result"])
        if _looks_like_placeholder(meta):
            raise RuntimeError(f"metadata extraction returned a placeholder stub: {meta}")
        return meta

    return retry(call, max_attempts=10, base_delay=30, what="metadata extraction")
