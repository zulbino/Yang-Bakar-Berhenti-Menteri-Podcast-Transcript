"""Shared helpers for the transcription pipeline."""
import re
import time
import yaml


def slugify(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:60]


def episode_slug(episode):
    date = episode["upload_date"]  # YYYYMMDD
    date_fmt = f"{date[0:4]}-{date[4:6]}-{date[6:8]}"
    return f"{date_fmt}-{slugify(episode['title'])}"


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
