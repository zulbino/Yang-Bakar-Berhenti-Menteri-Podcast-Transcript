"""Gemini calls for the transcription pipeline: raw transcription, editorial rewrite, translation, metadata.

Each episode is processed in a single call per stage (not chunked). gemini-3.5-flash
supports a 65,536-token output limit, comfortably covering even the longest (~3.5hr)
episode's raw transcript (~30k words). The audio is uploaded as a standalone file
(no video track) via the Files API -- referencing a YouTube URL directly loads the
full video at a much higher per-second token rate regardless of any offset given,
which blows the 1,048,576-token input limit for anything beyond roughly an hour.
"""
import json
import time

from google import genai
from google.genai import types

from common import retry

# gemini-3.7-flash returned sustained 503 UNAVAILABLE (high demand) across repeated
# test runs, including a live probe against 5 models where it was the only failure --
# likely capacity strain since it's a very recently launched model. Using
# gemini-3.6-flash everywhere instead since it passed consistently.
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
3. Keep Malay quotes in polished Malay and English quotes in clean English. Do not translate between languages; you may add a short bracketed translation of an idiom only if it aids clarity.
4. Do not include timestamps.
5. Cover the full conversation, from opening to close; do not truncate or summarize the tail end.
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
5. Translate the full interview end to end; do not truncate or summarize the tail end.
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


def transcribe_raw(client, audio_file, duration_human):
    prompt = RAW_PROMPT_TEMPLATE.format(duration=duration_human)

    def call():
        resp = client.models.generate_content(
            model=RAW_MODEL,
            contents=[types.Content(parts=[types.Part(file_data=types.FileData(file_uri=audio_file.uri, mime_type=audio_file.mime_type)), types.Part(text=prompt)])],
            config=types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS),
        )
        return _text(resp)

    return retry(call, max_attempts=10, base_delay=30, what="raw transcription")


def rewrite_clean(client, raw_text):
    prompt = CLEAN_PROMPT_TEMPLATE.format(raw_text=raw_text)

    def call():
        resp = client.models.generate_content(model=TEXT_MODEL, contents=[prompt], config=types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS))
        return _text(resp)

    return retry(call, max_attempts=10, base_delay=30, what="clean rewrite")


def translate(client, mixed_text, target_language):
    prompt = TRANSLATE_PROMPT_TEMPLATE.format(target_language=target_language, mixed_text=mixed_text)

    def call():
        resp = client.models.generate_content(model=TEXT_MODEL, contents=[prompt], config=types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS))
        return _text(resp)

    return retry(call, max_attempts=10, base_delay=30, what=f"translate to {target_language}")


def extract_metadata(client, clean_text):
    prompt = META_PROMPT_TEMPLATE.format(clean_text=clean_text)
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=META_SCHEMA, safety_settings=SAFETY_SETTINGS)

    def call():
        resp = client.models.generate_content(model=TEXT_MODEL, contents=[prompt], config=config)
        return json.loads(_text(resp))

    return retry(call, max_attempts=10, base_delay=30, what="metadata extraction")
