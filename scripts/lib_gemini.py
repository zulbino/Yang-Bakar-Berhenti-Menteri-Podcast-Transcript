"""Gemini calls for the transcription pipeline: raw transcription, editorial rewrite, translation, metadata.

Each episode is processed in a single call per stage (not chunked). gemini-3.5-flash
supports a 65,536-token output limit, comfortably covering even the longest (~3.5hr)
episode's raw transcript (~30k words). The audio is uploaded as a standalone file
(no video track) via the Files API -- referencing a YouTube URL directly loads the
full video at a much higher per-second token rate regardless of any offset given,
which blows the 1,048,576-token input limit for anything beyond roughly an hour.
"""
import json
import re
import time

from google import genai
from google.genai import types

from common import human_duration, retry

# gemini-3.7-flash has repeatedly hit sustained 503 UNAVAILABLE (high demand) across
# multiple test attempts since its Aug 13 launch. gemini-3.6-flash has been reliable
# throughout; pricing is identical, so there's no upside to retrying 3.7-flash.
RAW_MODEL = "gemini-3.6-flash"
TEXT_MODEL = "gemini-3.6-flash"

# This is a political podcast discussing corruption inquiries, scandals, and named
# public figures -- content Gemini's default safety filters (esp. civic integrity /
# prohibited-content categories) can block outright even though it's legitimate news
# commentary. Relax all categories since this pipeline only processes Rafizi Ramli's
# own published podcast audio, not user-generated prompts.
SAFETY_SETTINGS = [
    types.SafetySetting(category=category, threshold=types.HarmBlockThreshold.BLOCK_NONE)
    for category in (
        types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        types.HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
    )
]

RAW_PROMPT_TEMPLATE = """You are transcribing a Malaysian political podcast/interview featuring Rafizi Ramli, {duration} long. Speakers switch between English and Bahasa Melayu mid-sentence (code-switching / "Bahasa Rojak").

Produce a raw, close-to-verbatim transcript of the ENTIRE episode from start to finish:
- Label each speaker turn with their name if stated/identifiable in the audio, otherwise "Speaker 1" / "Speaker 2" etc, kept consistent across turns.
- Insert an approximate timestamp in [MM:SS] (or [H:MM:SS] past the first hour) at the start of each speaker turn.
- Transcribe Malay speech in Malay and English speech in English, exactly as spoken. Do not translate.
- You may lightly clean up filler sounds (um, ah, eh) and obvious stutters for readability, but do NOT paraphrase, summarize, or reword sentences. Preserve the speaker's actual word choices and sentence structure.
- Do not add commentary, headers, or anything besides the transcript itself.
- If a stretch is silent, music, or an ad break, note it briefly in brackets, e.g. [music/intro].
- Cover the full episode; do not stop early or summarize the tail end.

Output plain text only, no markdown formatting, no frontmatter."""

CLEAN_PROMPT_TEMPLATE = """You are an experienced journalist producing a newspaper-style Q&A interview from a raw podcast transcript.

Below is the full raw transcript of a Malaysian political podcast/interview featuring Rafizi Ramli, mixing English and Bahasa Melayu.

Task:
1. Rewrite it into a clean, professional Q&A format using Markdown bold speaker labels (e.g. "**Rafizi Ramli:** ...") with the actual speaker names from the transcript.
2. Smooth out spoken awkwardness, filler words, false starts, and repetition, while preserving the speaker's true intent, tone, and key points. Do not invent or omit substantive claims.
3. Preserve the language of each clause or phrase exactly as spoken, including mid-sentence code-switching (e.g. a sentence that starts in English and finishes in Malay must stay that way). Do not normalize a mixed-language sentence into a single language. Only polish grammar and remove filler within each language segment; do not translate any segment into the other language. You may add a short bracketed translation of an idiom only if it aids clarity.
4. Do not include timestamps.
5. This may be a partial excerpt of a longer conversation rather than the whole thing. Rewrite everything given to you in full -- this is a rewrite, not a summary. Do not condense multiple turns into one, skip exchanges, or shorten the overall length; the output should be comparably comprehensive to the input, just polished.
6. Output pure Markdown Q&A body text only. No YAML frontmatter, no top-level title heading.

Raw transcript:
---
{raw_text}
---"""

TRANSLATE_PROMPT_TEMPLATE = """You are a professional translator turning a bilingual (English/Bahasa Melayu) newspaper-style Q&A interview into a single-language version in {target_language}.

Below is the mixed-language version (English and Malay used interchangeably, matching how the speakers actually spoke).

Task:
1. Translate the entire interview into fluent, natural {target_language}, including any Malay or English quotes.
2. Preserve the exact Q&A structure and Markdown speaker labels (e.g. "**Rafizi Ramli:** ...").
3. Preserve all substantive facts, figures, and claims exactly. Do not add or drop content.
4. Keep proper nouns, acronyms, and terms with no natural equivalent as-is (e.g. "PADU", "GST", agency and person names).
5. This may be a partial excerpt of a longer interview rather than the whole thing. Translate everything given to you in full; do not condense, shorten, or summarize any part of it.
6. Output pure Markdown Q&A body text only. No YAML frontmatter, no top-level title heading.

Mixed-language version:
---
{mixed_text}
---"""

META_PROMPT_TEMPLATE = """Read the following full newspaper-style interview transcript from Rafizi Ramli's own podcast/YouTube channel. Based only on its content, extract metadata.

Rafizi Ramli is always the host/owner of this show, even in episodes where other speakers ask him most of the questions. Always include "Rafizi Ramli" in "hosts". Put any other named speakers (co-hosts, interviewers, journalists, analysts) in "guests" -- unless the episode is explicitly framed as Rafizi interviewing an external guest on a specific topic, in which case that person is the "guest" and any other regular co-host stays in "hosts".

Transcript:
---
{clean_text}
---"""

META_SCHEMA = {
    "type": "object",
    "properties": {
        "hosts": {"type": "array", "items": {"type": "string"}},
        "guests": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hosts", "guests", "summary", "topics"],
}


def _text(resp):
    """resp.text is None when the model returns no usable text part (e.g. safety
    block, empty candidate) even though the HTTP call itself succeeded. Raise so
    retry() treats it as a failed attempt instead of propagating None downstream."""
    if resp.text is None:
        candidate = resp.candidates[0] if resp.candidates else None
        finish_reason = candidate.finish_reason if candidate else None
        raise RuntimeError(f"empty response text (finish_reason={finish_reason}, prompt_feedback={resp.prompt_feedback})")
    return resp.text


def get_client():
    # Without an explicit timeout, a stalled request can hang indefinitely and
    # never reach our retry() wrapper's except block.
    return genai.Client(http_options=types.HttpOptions(timeout=600_000))  # 10 min, in ms


def upload_audio(client, audio_path):
    # The SDK auto-detects .m4a as mime type "video/m4a", which Gemini fails to
    # process server-side (no video track). Force the correct audio mime type.
    file = client.files.upload(file=str(audio_path), config=types.UploadFileConfig(mime_type="audio/mp4"))
    while file.state.name == "PROCESSING":
        time.sleep(5)
        file = client.files.get(name=file.name)
    if file.state.name != "ACTIVE":
        raise RuntimeError(f"audio upload failed, state={file.state.name}")
    return file


MAX_OUTPUT_TOKENS = 65536

CONTINUE_PROMPT = (
    "Continue the transcript exactly from where you left off. Do not repeat any "
    "earlier lines, do not add commentary or a preamble, and do not restart the "
    "timestamp count — pick up at the next moment in the audio."
)


def _finish_reason_name(resp):
    candidate = resp.candidates[0] if resp.candidates else None
    reason = candidate.finish_reason if candidate else None
    return getattr(reason, "name", str(reason))


def _generate_with_continuation(client, model, config, initial_parts):
    # A single response can hit MAX_OUTPUT_TOKENS well before a long episode's
    # transcript/rewrite/translation is complete; keep asking the model to
    # continue in the same conversation until it finishes naturally, capped to
    # avoid a runaway loop.
    contents = [types.Content(role="user", parts=initial_parts)]
    full_text = ""
    for _ in range(8):
        resp = client.models.generate_content(model=model, contents=contents, config=config)
        text = _text(resp)
        full_text += text
        if _finish_reason_name(resp) != "MAX_TOKENS":
            return full_text
        contents.append(types.Content(role="model", parts=[types.Part(text=text)]))
        contents.append(types.Content(role="user", parts=[types.Part(text=CONTINUE_PROMPT)]))
    raise RuntimeError(f"{model} still hitting MAX_TOKENS after 8 continuations")


_TIMESTAMP_RE = re.compile(r"\[(?:(\d+):)?(\d+):(\d+)\]")


def _last_timestamp_seconds(text):
    matches = _TIMESTAMP_RE.findall(text)
    if not matches:
        return 0
    h, m, s = matches[-1]
    return (int(h) if h else 0) * 3600 + int(m) * 60 + int(s)


def _trim_dangling_fragment(text):
    """The response hitting MAX_OUTPUT_TOKENS exactly once the 95% coverage
    threshold is reached can leave a half-written final line/turn (e.g. a bare
    "[3:1" with no closing bracket or speaker text). Drop a trailing block that
    doesn't end in normal sentence punctuation."""
    blocks = text.rstrip().split("\n\n")
    if blocks and not re.search(r'[.!?\]"\')]\s*$', blocks[-1]):
        blocks = blocks[:-1]
    return "\n\n".join(blocks) + "\n"


def transcribe_raw(client, audio_file, duration_human, duration_seconds):
    prompt = RAW_PROMPT_TEMPLATE.format(duration=duration_human)
    audio_part = types.Part(file_data=types.FileData(file_uri=audio_file.uri, mime_type=audio_file.mime_type))
    config = types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS, max_output_tokens=MAX_OUTPUT_TOKENS)

    def call():
        # The model sometimes stops (finish_reason STOP, not MAX_TOKENS) well
        # before the end of a long episode, as if it decided the transcript was
        # "done." Keep forcing continuations, using the last timestamp actually
        # emitted (not the model's own say-so) to judge whether it truly reached
        # the end, until coverage is close enough or the round cap is hit.
        contents = [types.Content(role="user", parts=[audio_part, types.Part(text=prompt)])]
        full_text = ""
        for round_num in range(15):
            resp = client.models.generate_content(model=RAW_MODEL, contents=contents, config=config)
            text = _text(resp)
            full_text += text
            covered = _last_timestamp_seconds(full_text)
            if covered >= duration_seconds * 0.95:
                return _trim_dangling_fragment(full_text)
            remaining_human = human_duration(max(duration_seconds - covered, 0))
            contents.append(types.Content(role="model", parts=[types.Part(text=text)]))
            contents.append(types.Content(role="user", parts=[types.Part(text=(
                f"The transcript is not finished -- you have only covered up to roughly "
                f"{covered // 60}:{covered % 60:02d} out of {duration_human} total. "
                f"{CONTINUE_PROMPT} There is still about {remaining_human} of audio left; "
                "keep going until you reach the actual end of the episode."
            ))]))
        raise RuntimeError(f"raw transcription still incomplete after 15 continuation rounds (reached ~{_last_timestamp_seconds(full_text)}s of {duration_seconds}s)")

    return retry(call, max_attempts=10, base_delay=30, what="raw transcription")


# Handing a multi-hour transcript to the model in one shot risks it choosing to
# summarize/condense rather than fully rewrite -- it finishes cleanly (STOP, not
# MAX_TOKENS) so the continuation loop never catches it. Chunking keeps each
# call small enough that full-coverage rewriting is the natural, easy answer.
CHUNK_CHARS = 40_000


def _split_into_chunks(text, max_chars):
    blocks = text.split("\n\n")
    chunks = []
    current, current_len = [], 0
    for block in blocks:
        block_len = len(block) + 2
        if current and current_len + block_len > max_chars:
            chunks.append("\n\n".join(current))
            current, current_len = [], 0
        current.append(block)
        current_len += block_len
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def rewrite_clean(client, raw_text):
    config = types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS, max_output_tokens=MAX_OUTPUT_TOKENS)
    chunks = _split_into_chunks(raw_text, CHUNK_CHARS)

    results = []
    for chunk in chunks:
        prompt = CLEAN_PROMPT_TEMPLATE.format(raw_text=chunk)

        def call(prompt=prompt):
            return _generate_with_continuation(client, TEXT_MODEL, config, [types.Part(text=prompt)])

        results.append(retry(call, max_attempts=10, base_delay=30, what="clean rewrite"))
    return "\n\n".join(results)


def translate(client, mixed_text, target_language):
    config = types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS, max_output_tokens=MAX_OUTPUT_TOKENS)
    chunks = _split_into_chunks(mixed_text, CHUNK_CHARS)

    results = []
    for chunk in chunks:
        prompt = TRANSLATE_PROMPT_TEMPLATE.format(target_language=target_language, mixed_text=chunk)

        def call(prompt=prompt):
            return _generate_with_continuation(client, TEXT_MODEL, config, [types.Part(text=prompt)])

        results.append(retry(call, max_attempts=10, base_delay=30, what=f"translate to {target_language}"))
    return "\n\n".join(results)


def extract_metadata(client, clean_text):
    prompt = META_PROMPT_TEMPLATE.format(clean_text=clean_text)
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=META_SCHEMA, safety_settings=SAFETY_SETTINGS)

    def call():
        resp = client.models.generate_content(model=TEXT_MODEL, contents=[prompt], config=config)
        return json.loads(_text(resp))

    return retry(call, max_attempts=10, base_delay=30, what="metadata extraction")
