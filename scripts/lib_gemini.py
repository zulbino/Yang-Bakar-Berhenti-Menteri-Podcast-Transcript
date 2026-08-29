"""Gemini calls for the transcription pipeline: raw transcription, editorial rewrite, translation, metadata.

Each episode is processed in a single call per stage (not chunked). Every model in
MODEL_FALLBACK_CHAIN supports a 65,536-token output limit, comfortably covering even
the longest (~3.5hr) episode's raw transcript (~30k words). The audio is uploaded as a standalone file
(no video track) via the Files API -- referencing a YouTube URL directly loads the
full video at a much higher per-second token rate regardless of any offset given,
which blows the 1,048,576-token input limit for anything beyond roughly an hour.
"""
import json
import re
import time

from google import genai
from google.genai import errors, types

from common import human_duration, retry

# Free-tier daily quota (20 requests/day) is tracked per-model, independently of
# every other model. When one model's free-tier quota is exhausted (detected via
# the RESOURCE_EXHAUSTED + FreeTier error), every subsequent call in this process
# automatically moves on to the next model in the chain, so a run can keep going
# across all offered models until the daily reset instead of stalling on the
# first one hit.
#
# gemini-3.7-flash previously hit sustained 503 UNAVAILABLE (high demand) since
# its Aug 13 launch -- Google-side capacity, not quota -- so it was excluded
# outright. Re-added once that congestion reportedly cleared, but 503 isn't a
# quota-exhaustion signal, so it needs its own handling: a couple of quick
# retries on the same model (a single transient 503 self-recovers most of the
# time, seen directly in this project's own testing), then advance to the next
# model if it's still unavailable, rather than wasting the full slow backoff
# budget on a model that's genuinely down.
#
# Ordered best-quality-first, not just by version number. Every model here can
# also silently drop mixed-language code-switching under load -- confirmed
# directly on gemini-3.1-flash-lite (see the language-mistranslation writeup) --
# so degradation-prone models sit at the end, reached only once everything
# better is genuinely exhausted or down. qa_check.py's language-density check
# is what catches it if a weak fallback model does mistranslate; it no longer
# passes silently. gemini-3.1-pro-preview and gemini-2.5-pro are included for
# quota diversity (each model's free-tier quota is independent, see above) --
# kept as a last resort rather than a first choice. gemini-2.5-flash and
# gemini-2.5-flash-lite used to round out this tier but both 404 with "no
# longer available to new users" on this project -- confirmed directly, not
# just quota-exhausted -- so they're replaced with the "-latest" rolling
# aliases (gemini-flash-latest / gemini-flash-lite-latest), which stay
# pointed at whatever generation Google currently serves instead of a pinned
# version that can be retired later.
MODEL_FALLBACK_CHAIN = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-2.5-pro",
    "gemini-flash-latest",
    "gemini-flash-lite-latest",
]
_model_idx = 0
UNAVAILABLE_RETRIES_BEFORE_FALLBACK = 2
UNAVAILABLE_RETRY_DELAY_SECONDS = 10


def current_model():
    return MODEL_FALLBACK_CHAIN[_model_idx]


def _is_free_tier_quota_exhausted(e):
    # The literal "FreeTier" string only appears in the nested quotaId field
    # inside e.details (e.g. "GenerateRequestsPerDayPerProjectPerModel-FreeTier"),
    # not in e.message, which just says "...generate_content_free_tier_requests...".
    return (
        isinstance(e, errors.ClientError)
        and e.code == 429
        and e.status == "RESOURCE_EXHAUSTED"
        and "freetier" in str(e.details).lower()
    )


def _is_unavailable(e):
    return isinstance(e, errors.ServerError) and e.code == 503


def _is_model_not_found(e):
    # A wrong/deprecated model ID in MODEL_FALLBACK_CHAIN (e.g. missing a "-preview"
    # suffix) 404s identically on every retry -- confirmed directly when
    # "gemini-3.1-pro" (should have been "gemini-3.1-pro-preview") burned a full
    # 10-attempt backoff on every episode that reached it before failing outright.
    # Advance past it like any other unusable model instead of retrying a name that
    # will never resolve.
    return isinstance(e, errors.ClientError) and e.code == 404


def _is_prohibited_content_block(resp):
    # PROHIBITED_CONTENT is a built-in Google safety layer, separate from and not
    # disabled by SAFETY_SETTINGS below (that only covers the 5 adjustable harm
    # categories) -- it's a hard, non-configurable block. Confirmed to trip more
    # readily on newer models (gemini-3.7/3.6-flash) for audio discussing real named
    # public figures and corruption allegations. Retrying the same model is pointless
    # since the classification is deterministic; switching model is the only lever.
    feedback = resp.prompt_feedback
    return bool(feedback) and feedback.block_reason == types.BlockedReason.PROHIBITED_CONTENT


def _advance_model(reason):
    global _model_idx
    if _model_idx + 1 >= len(MODEL_FALLBACK_CHAIN):
        return False
    _model_idx += 1
    print(f"  [fallback] switching to {current_model()} ({reason})", flush=True)
    return True


def generate_content(client, contents, config):
    """generate_content with automatic model fallback on free-tier quota exhaustion,
    sustained model unavailability (503), a nonexistent/deprecated model (404), or a
    hard PROHIBITED_CONTENT safety block."""
    unavailable_streak = 0
    while True:
        try:
            resp = client.models.generate_content(model=current_model(), contents=contents, config=config)
        except errors.APIError as e:
            if _is_free_tier_quota_exhausted(e):
                if _advance_model("free-tier quota exhausted"):
                    unavailable_streak = 0
                    continue
                raise
            if _is_model_not_found(e):
                if _advance_model("model not found"):
                    unavailable_streak = 0
                    continue
                raise
            if _is_unavailable(e):
                unavailable_streak += 1
                if unavailable_streak <= UNAVAILABLE_RETRIES_BEFORE_FALLBACK:
                    time.sleep(UNAVAILABLE_RETRY_DELAY_SECONDS)
                    continue
                if _advance_model("model unavailable"):
                    unavailable_streak = 0
                    continue
            raise
        else:
            if _is_prohibited_content_block(resp):
                if _advance_model("prohibited content block"):
                    continue
                raise RuntimeError("prohibited content block persisted through every model in the fallback chain")
            unavailable_streak = 0
            return resp

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
1. Rewrite it into a clean, professional Q&A format using Markdown bold speaker labels, i.e. a line beginning "**<speaker>:** " for each turn. Copy each speaker label from the transcript EXACTLY as it appears there. Never replace a name with a role or description: if the transcript says "Haziq:", the label is "**Haziq:**" and never "**Host:**", "**Interviewer:**", "**Moderator:**", "**Co-host:**", "**Questioner:**" or similar. Where the transcript itself gives no name -- "Speaker 1:", "Speaker ?:" -- keep that marker verbatim rather than inventing a role for it; an unnamed speaker must stay visibly unnamed. Do not merge two differently-labelled speakers under one label, and do not translate a label.
2. Smooth out spoken awkwardness, filler words, false starts, and repetition, while preserving the speaker's true intent, tone, and key points. Do not invent or omit substantive claims.
3. Preserve the language of each clause or phrase exactly as spoken, including mid-sentence code-switching (e.g. a sentence that starts in English and finishes in Malay must stay that way). Do not normalize a mixed-language sentence into a single language. Only polish grammar and remove filler within each language segment; do not translate any segment into the other language. You may add a short bracketed translation of an idiom only if it aids clarity. As a concrete floor, mirroring the length floor in point 5: Malay must remain about as dense in your output as in the input. Count the common Malay function words ("yang", "tak", "kan", "ni", "tu", "lah", "dia", "kita", "sebab", "macam", "dengan", "untuk", "boleh", "kalau", "je", "pun") in the input chunk, and your output should carry at least 80% of that count. If your draft comes in lower, you have anglicised code-switched speech; go back and restore the Malay wording before returning your answer.
4. Do not include timestamps.
5. This may be a partial excerpt of a longer conversation rather than the whole thing. Rewrite everything given to you in full -- this is a rewrite, not a summary. Do not condense multiple turns into one, skip exchanges, or shorten the overall length; the output should be comparably comprehensive to the input, just polished. This applies even when a stretch feels repetitive, rambling, or heavy with filler particles ("kan", "ah", "hmm", "lah") or casual tangents -- rewrite that stretch in full rather than compressing or summarizing it away. As a concrete floor: your output for this chunk should be at least 70% of the input transcript's character length. If your draft comes in shorter than that, go back and expand it before returning your answer, rather than submitting a condensed version.
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

TOPICS. These episodes run two to three hours and move through many distinct subjects, so the list must cover the WHOLE episode, not just its opening. Work through the transcript start to finish and give one entry for each subject that gets sustained discussion -- typically 8 to 15 entries. Requirements:

- Name the SUBJECT, not the speaker. A guest's name is not a topic; they are already recorded in "guests". Write "Gen Z identity and generational politics", never "Zaim Zulkifli".
- Name the specific thing being discussed, using the words the episode itself uses: an organisation, policy, scheme, company, place, law or named controversy. Write "Pemansuhan AUKU dan reformasi pendidikan tinggi", "KWAP investment in e-Fishery and due diligence failures", "Krisis pelarian Rohingya di Malaysia" -- not "education policy", "an investment issue" or "a refugee discussion".
- The episode's MAIN theme must be present. The title is a strong clue to what it is; if the title names something, a topic entry must cover it.
- Keep each entry to one line, and keep the language of the discussion (Malay episodes get Malay entries).
- Cover the recurring segments too when they carry real content, including the weekly "Beria" viral roundup, guest interviews and the closing questions.

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


def upload_audio(client, audio_path, mime_type="audio/mp4"):
    # The SDK auto-detects .m4a as mime type "video/m4a", which Gemini fails to
    # process server-side (no video track). Force the correct audio mime type.
    file = client.files.upload(file=str(audio_path), config=types.UploadFileConfig(mime_type=mime_type))
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


def _generate_with_continuation(client, config, initial_parts):
    # A single response can hit MAX_OUTPUT_TOKENS well before a long episode's
    # transcript/rewrite/translation is complete; keep asking the model to
    # continue in the same conversation until it finishes naturally, capped to
    # avoid a runaway loop.
    contents = [types.Content(role="user", parts=initial_parts)]
    full_text = ""
    for round_index in range(8):
        resp = generate_content(client, contents, config)
        text = _text(resp)
        if round_index == 0:
            full_text = text
        else:
            before = len(full_text)
            full_text, dropped = _drop_reemitted_prefix(full_text, text)
            if dropped:
                print(f"  continuation round {round_index}: dropped {dropped} "
                      f"re-emitted turn(s) already covered")
            if len(full_text) <= before:
                raise RuntimeError(
                    f"{model} continuation round {round_index} added no new content "
                    f"(re-emitted {dropped} covered turn(s)) -- see ENGINEERING_LOG.md 1.22")
        if _finish_reason_name(resp) != "MAX_TOKENS":
            return full_text
        contents.append(types.Content(role="model", parts=[types.Part(text=text)]))
        contents.append(types.Content(role="user", parts=[types.Part(text=CONTINUE_PROMPT)]))
    raise RuntimeError(f"{model} still hitting MAX_TOKENS after 8 continuations")


def _split_turns(text):
    """Split a chunk into turns at each timestamp marker. Blank lines between
    turns are not reliable here -- _normalize_turn_breaks runs later in the
    pipeline -- so anchor on the marker instead."""
    positions = [m.start() for m in _TIMESTAMP_RE.finditer(text)]
    if not positions:
        return [text] if text else []
    turns = [text[:positions[0]]] if positions[0] > 0 else []
    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        turns.append(text[start:end])
    return turns


def _turn_key(turn):
    """Compare turns by their words alone: a re-emission typically reappears
    under a fresh timestamp, so the marker itself must not be part of the key."""
    return " ".join(_TIMESTAMP_RE.sub(" ", turn).lower().split())


def _drop_reemitted_prefix(full_text, chunk):
    """Strip a continuation chunk's leading turns that repeat ground already
    collected (ENGINEERING_LOG.md 1.22). Only the prefix is stripped: real speech
    does repeat, so a later restatement inside the chunk is left for the
    duplicate-block tooling to judge rather than silently removed here."""
    turns = _split_turns(full_text)
    if not turns:
        return full_text + chunk, 0
    # Everything but the final turn is definitely complete; the final one may
    # have been cut mid-sentence by MAX_TOKENS.
    seen = {key for key in (_turn_key(t) for t in turns[:-1]) if key}
    new = _split_turns(chunk)
    tail_key = _turn_key(turns[-1])
    dropped = 0
    # If the cut-off turn is restated in full at the head of this chunk, keep the
    # complete version instead of gluing the restatement onto the fragment.
    if new and tail_key and _turn_key(new[0]).startswith(tail_key[:max(40, len(tail_key) // 2)]):
        full_text = full_text[:len(full_text) - len(turns[-1])]
    while new and _turn_key(new[0]) in seen:
        new.pop(0)
        dropped += 1
    return full_text + "".join(new), dropped


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
    if len(blocks) > 1 and not re.search(r'[.!?\]"\')]\s*$', blocks[-1]):
        blocks = blocks[:-1]
    return "\n\n".join(blocks) + "\n"


def _normalize_turn_breaks(text):
    """The model can occasionally omit the blank line between speaker turns,
    producing one run-on paragraph with no "\n\n" anywhere. That silently
    defeats _split_into_chunks (which splits on "\n\n"), letting an oversized
    block bypass chunking entirely and get sent to the model in a single call
    -- exactly the failure mode CHUNK_CHARS exists to prevent. Force a blank
    line before every timestamp marker so each turn is its own paragraph."""
    text = re.sub(r"[ \t\n]*(?=\[(?:\d+:)?\d+:\d+\])", "\n\n", text)
    # The substitution above matches twice at every boundary -- once consuming
    # the real preceding whitespace, then again as a redundant zero-width match
    # at the same resulting position -- doubling every blank line. Collapse the
    # artifact rather than chase the regex engine's match-order quirk.
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.lstrip("\n")


def _canonicalize_timestamps(text):
    """The model sometimes writes a long episode's timestamp as two-part
    [MM:SS] even once MM exceeds 59 (e.g. [96:37] instead of [1:36:37]) --
    numerically equivalent (every consumer here parses MM as unbounded
    minutes, so the total-seconds value is identical either way) but
    inconsistent with how the same episode formats timestamps past the first
    hour everywhere else. Roll over to canonical H:MM:SS."""
    def roll_over(m):
        minutes, seconds = int(m.group(1)), m.group(2)
        if minutes < 60:
            return m.group(0)
        hours, minutes = divmod(minutes, 60)
        return f"[{hours}:{minutes:02d}:{seconds}]"
    return re.sub(r"\[(\d+):(\d\d)\]", roll_over, text)


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
            resp = generate_content(client, contents, config)
            text = _text(resp)
            full_text += text
            covered = _last_timestamp_seconds(full_text)
            if covered > duration_seconds * 1.5:
                # The model can degenerate into repeating short bracketed tags
                # (e.g. "[music]", "[laughter]") with fabricated, ever-increasing
                # timestamps instead of real transcript content. A timestamp far
                # beyond the actual audio duration is itself evidence of this,
                # not genuine coverage -- treat it as a failed attempt so retry()
                # starts a fresh conversation instead of accepting the garbage.
                raise RuntimeError(
                    f"raw transcription timestamps ran away: last timestamp {covered}s "
                    f"is far beyond the audio's {duration_seconds}s duration (likely a "
                    "hallucination loop, not real coverage)"
                )
            if covered >= duration_seconds * 0.95:
                return _trim_dangling_fragment(_canonicalize_timestamps(_normalize_turn_breaks(full_text)))
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
    # A "\n\n"-delimited block can itself exceed max_chars (e.g. a raw
    # transcript missing turn breaks). Left alone it would bypass chunking
    # entirely and get sent to the model in one oversized call -- hard-slice
    # it so the size cap this function exists to enforce always holds.
    blocks = [b[i:i + max_chars] for b in blocks for i in range(0, len(b), max_chars)] or [""]
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
            return _generate_with_continuation(client, config, [types.Part(text=prompt)])

        results.append(retry(call, max_attempts=10, base_delay=30, what="clean rewrite"))
    return "\n\n".join(results)


def translate(client, mixed_text, target_language):
    config = types.GenerateContentConfig(safety_settings=SAFETY_SETTINGS, max_output_tokens=MAX_OUTPUT_TOKENS)
    chunks = _split_into_chunks(mixed_text, CHUNK_CHARS)

    results = []
    for chunk in chunks:
        prompt = TRANSLATE_PROMPT_TEMPLATE.format(target_language=target_language, mixed_text=chunk)

        def call(prompt=prompt):
            return _generate_with_continuation(client, config, [types.Part(text=prompt)])

        results.append(retry(call, max_attempts=10, base_delay=30, what=f"translate to {target_language}"))
    return "\n\n".join(results)


def extract_metadata(client, clean_text):
    prompt = META_PROMPT_TEMPLATE.format(clean_text=clean_text)
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=META_SCHEMA, safety_settings=SAFETY_SETTINGS)

    def call():
        resp = generate_content(client, [prompt], config)
        return json.loads(_text(resp))

    return retry(call, max_attempts=10, base_delay=30, what="metadata extraction")
