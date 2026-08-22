"""Shared helpers for the transcription pipeline."""
import re
import time
import yaml


def slugify(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:60]


# The show was renamed from "Yang Bakar Menteri" to "Yang Berhenti Menteri" partway
# through; this episode sits at that transition and carries no number in its title.
EPISODE_NUMBER_OVERRIDES = {"2k8hW9hDvGE": 0}

# The 6 episodes under the original show name, all from 2024 -- a closed, historical
# set that won't grow now that the show has been renamed. Everything else (including
# the 2k8hW9hDvGE transition episode above, titled "Podcast Yang Berhenti Menteri?")
# belongs under the current name.
YANG_BAKAR_MENTERI_VIDEO_IDS = {
    "c9JQ9BoGJms", "WT1m_Yl5E_M", "Y2o4gIQAlwc",
    "lNmIx3ssUIM", "AHAa0a58w64", "-tpyLr5kwxI",
}


def show_era_dir(episode):
    if episode["video_id"] in YANG_BAKAR_MENTERI_VIDEO_IDS:
        return "yang-bakar-menteri"
    return "yang-berhenti-menteri"

_EPISODE_NUMBER_RE = re.compile(r"(?:Episod|EP)\s*#?(\d+)|#(\d+)", re.IGNORECASE)


def episode_number(episode):
    if episode["video_id"] in EPISODE_NUMBER_OVERRIDES:
        return EPISODE_NUMBER_OVERRIDES[episode["video_id"]]
    m = _EPISODE_NUMBER_RE.search(episode["title"])
    return int(m.group(1) or m.group(2)) if m else None


def episode_slug(episode):
    date = episode["upload_date"]  # YYYYMMDD
    date_fmt = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    num = episode_number(episode)
    ep_part = f"ep{num:02d}-" if num is not None else ""
    return f"{date_fmt}-{ep_part}{slugify(episode['title'])}"


def episode_path(episode):
    """Path (relative to EPISODES_DIR) to this episode's folder, e.g.
    "yang-berhenti-menteri/2025-06-20-ep01-yang-berhenti-menteri-1"."""
    return f"{show_era_dir(episode)}/{episode_slug(episode)}"


def human_duration(seconds):
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s}s"


def frontmatter_md(fields, body):
    yaml_text = yaml.dump(fields, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return f"---\n{yaml_text}---\n\n{body}\n"


def read_frontmatter_body(path):
    """Split a frontmatter_md()-written file into (fields, body), dropping the leading '# Heading' line."""
    text = path.read_text(encoding="utf-8")
    _, yaml_text, body = text.split("---", 2)
    fields = yaml.safe_load(yaml_text)
    body = body.strip()
    if body.startswith("#"):
        body = body.split("\n", 1)[1].lstrip()
    return fields, body


def retry(fn, max_attempts=5, base_delay=10, what=""):
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            delay = base_delay * attempt
            print(f"  [retry] {what} attempt {attempt}/{max_attempts} failed: {e}. Waiting {delay}s", flush=True)
            time.sleep(delay)
    raise last_err
