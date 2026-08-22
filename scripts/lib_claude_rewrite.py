"""Claude-based rewrite/translate/metadata fallback for the rewrite stage, used
when the Gemini API is unavailable (e.g. billing blocked). Mirrors lib_gemini.py's
rewrite_clean/translate/extract_metadata; the prompt templates and chunking logic
are imported from there since that text is provider-agnostic, not Gemini-specific.
"""
import json

import anthropic

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
MAX_TOKENS = 16000

CONTINUE_PROMPT = (
    "Continue exactly from where you left off. Do not repeat any earlier "
    "lines, and do not add commentary or a preamble."
)


def get_client():
    return anthropic.Anthropic()


def _generate_with_continuation(client, prompt):
    # A single response can hit max_tokens before a long chunk's rewrite/
    # translation is complete; keep asking the model to continue in the same
    # conversation until it finishes naturally, capped to avoid a runaway loop.
    messages = [{"role": "user", "content": prompt}]
    full_text = ""
    for _ in range(8):
        resp = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS, messages=messages)
        text = next((b.text for b in resp.content if b.type == "text"), "")
        full_text += text
        if resp.stop_reason != "max_tokens":
            return full_text
        messages.append({"role": "assistant", "content": resp.content})
        messages.append({"role": "user", "content": CONTINUE_PROMPT})
    raise RuntimeError(f"{MODEL} still hitting max_tokens after 8 continuations")


def rewrite_clean(client, raw_text):
    chunks = _split_into_chunks(raw_text, CHUNK_CHARS)

    results = []
    for chunk in chunks:
        prompt = CLEAN_PROMPT_TEMPLATE.format(raw_text=chunk)

        def call(prompt=prompt):
            return _generate_with_continuation(client, prompt)

        results.append(retry(call, max_attempts=10, base_delay=30, what="clean rewrite"))
    return "\n\n".join(results)


def translate(client, mixed_text, target_language):
    chunks = _split_into_chunks(mixed_text, CHUNK_CHARS)

    results = []
    for chunk in chunks:
        prompt = TRANSLATE_PROMPT_TEMPLATE.format(target_language=target_language, mixed_text=chunk)

        def call(prompt=prompt):
            return _generate_with_continuation(client, prompt)

        results.append(retry(call, max_attempts=10, base_delay=30, what=f"translate to {target_language}"))
    return "\n\n".join(results)


def extract_metadata(client, clean_text):
    prompt = META_PROMPT_TEMPLATE.format(clean_text=clean_text)
    schema = {**META_SCHEMA, "additionalProperties": False}

    def call():
        resp = client.messages.create(
            model=MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = next(b.text for b in resp.content if b.type == "text")
        return json.loads(text)

    return retry(call, max_attempts=10, base_delay=30, what="metadata extraction")
