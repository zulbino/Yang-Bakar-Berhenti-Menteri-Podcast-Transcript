"""Gemini calls for the transcription pipeline: raw transcription, editorial rewrite, metadata extraction."""
import json

from google import genai
from google.genai import types

from common import mmss, retry

MODEL = "gemini-3.6-flash"

RAW_PROMPT_TEMPLATE = """You are transcribing a segment of a Malaysian political podcast/interview featuring Rafizi Ramli. Speakers switch between English and Bahasa Melayu mid-sentence (code-switching / "Bahasa Rojak").

Listen to the audio ONLY between timestamp {start} and {end} (mm:ss, relative to the start of this audio file).

Produce a raw, close-to-verbatim transcript of that segment:
- Label each speaker turn with their name if stated/identifiable in the audio, otherwise "Speaker 1" / "Speaker 2" etc, kept consistent across turns.
- Insert an approximate timestamp in [MM:SS] at the start of each speaker turn.
- Transcribe Malay speech in Malay and English speech in English, exactly as spoken. Do not translate.
- You may lightly clean up filler sounds (um, ah, eh) and obvious stutters for readability, but do NOT paraphrase, summarize, or reword sentences. Preserve the speaker's actual word choices and sentence structure.
- Do not add commentary, headers, or anything besides the transcript itself.
- If this range is silent, music, or an ad break, note it briefly in brackets, e.g. [music/intro].

Output plain text only, no markdown formatting, no frontmatter."""

CLEAN_PROMPT_TEMPLATE = """You are an experienced journalist producing a newspaper-style Q&A interview from a raw podcast transcript segment.

Below is a raw transcript excerpt from a Malaysian political podcast/interview featuring Rafizi Ramli, mixing English and Bahasa Melayu.

Task:
1. Rewrite it into a clean, professional Q&A format using Markdown bold speaker labels (e.g. "**Rafizi Ramli:** ...") with the actual speaker names from the transcript.
2. Smooth out spoken awkwardness, filler words, false starts, and repetition, while preserving the speaker's true intent, tone, and key points. Do not invent or omit substantive claims.
3. Keep Malay quotes in polished Malay and English quotes in clean English. Do not translate between languages; you may add a short bracketed translation of an idiom only if it aids clarity.
4. Do not include timestamps.
5. Output pure Markdown Q&A body text only. No YAML frontmatter, no top-level title heading.

Raw transcript excerpt:
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
5. Output pure Markdown Q&A body text only. No YAML frontmatter, no top-level title heading.

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


def get_client():
    # Without an explicit timeout, a stalled request can hang indefinitely and
    # never reach our retry() wrapper's except block.
    return genai.Client(http_options=types.HttpOptions(timeout=300_000))  # 5 min, in ms


def transcribe_raw_chunk(client, youtube_url, start_seconds, end_seconds):
    prompt = RAW_PROMPT_TEMPLATE.format(start=mmss(start_seconds), end=mmss(end_seconds))
    video_part = types.Part(file_data=types.FileData(file_uri=youtube_url))

    def call():
        resp = client.models.generate_content(
            model=MODEL,
            contents=[types.Content(parts=[video_part, types.Part(text=prompt)])],
        )
        return resp.text

    return retry(call, max_attempts=6, base_delay=15, what=f"raw chunk {mmss(start_seconds)}-{mmss(end_seconds)}")


def rewrite_clean_chunk(client, raw_text):
    prompt = CLEAN_PROMPT_TEMPLATE.format(raw_text=raw_text)

    def call():
        resp = client.models.generate_content(model=MODEL, contents=[prompt])
        return resp.text

    return retry(call, max_attempts=6, base_delay=15, what="clean rewrite chunk")


def translate_chunk(client, mixed_text, target_language):
    prompt = TRANSLATE_PROMPT_TEMPLATE.format(target_language=target_language, mixed_text=mixed_text)

    def call():
        resp = client.models.generate_content(model=MODEL, contents=[prompt])
        return resp.text

    return retry(call, max_attempts=6, base_delay=15, what=f"translate chunk to {target_language}")


def extract_metadata(client, clean_text):
    prompt = META_PROMPT_TEMPLATE.format(clean_text=clean_text)
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=META_SCHEMA)

    def call():
        resp = client.models.generate_content(model=MODEL, contents=[prompt], config=config)
        return json.loads(resp.text)

    return retry(call, max_attempts=6, base_delay=15, what="metadata extraction")
