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
import subprocess

from common import retry
from lib_gemini import (
    CHUNK_CHARS,
    CLEAN_PROMPT_TEMPLATE,
    META_PROMPT_TEMPLATE,
    META_SCHEMA,
    TRANSLATE_PROMPT_TEMPLATE,
    _split_into_chunks,
)

MODEL = "claude-sonnet-5"
CLAUDE_EXE = "claude"

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


def _run_claude(prompt, session_id=None, json_schema=None):
    cmd = [
        CLAUDE_EXE, "-p", "--output-format", "json", "--model", MODEL,
        "--safe-mode", "--disallowedTools", DISALLOWED_TOOLS,
    ]
    if session_id:
        cmd += ["--resume", session_id]
    else:
        cmd += ["--system-prompt", SYSTEM_PROMPT]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]

    proc = subprocess.run(cmd, input=prompt.encode("utf-8"), capture_output=True)
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


def rewrite_clean(client, raw_text):
    chunks = _split_into_chunks(raw_text, CHUNK_CHARS)

    results = []
    for chunk in chunks:
        prompt = CLEAN_PROMPT_TEMPLATE.format(raw_text=chunk)

        def call(prompt=prompt):
            return _generate_with_continuation(prompt)

        results.append(retry(call, max_attempts=10, base_delay=30, what="clean rewrite"))
    return "\n\n".join(results)


def translate(client, mixed_text, target_language):
    chunks = _split_into_chunks(mixed_text, CHUNK_CHARS)

    results = []
    for chunk in chunks:
        prompt = TRANSLATE_PROMPT_TEMPLATE.format(target_language=target_language, mixed_text=chunk)

        def call(prompt=prompt):
            return _generate_with_continuation(prompt)

        results.append(retry(call, max_attempts=10, base_delay=30, what=f"translate to {target_language}"))
    return "\n\n".join(results)


def extract_metadata(client, clean_text):
    prompt = META_PROMPT_TEMPLATE.format(clean_text=clean_text)
    schema = {**META_SCHEMA, "additionalProperties": False}

    def call():
        result = _run_claude(prompt, json_schema=schema)
        return json.loads(result["result"])

    return retry(call, max_attempts=10, base_delay=30, what="metadata extraction")
