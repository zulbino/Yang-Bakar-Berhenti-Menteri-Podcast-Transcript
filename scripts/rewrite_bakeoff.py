"""Run one transcript segment through several models on the same prompt, and measure.

WHY THIS EXISTS. Three cheap models were rejected for the rewrite stage on whole-episode
runs -- Haiku dropped about half a translation, a local Sailor2 truncated 32% and invented a
claim, Gemini finished 73-82% and split a name into three. None of that told us how a model
behaves on a 1,200-word segment, which is what `segment_episode.py` now produces, and the
answer turned out to be different for every model. So this measures rather than assumes, and
it measures the four things that have actually gone wrong in this repo's history:

  length      output characters over input characters -- catches truncation
  Malay       the density of Malay function words against the input -- catches the model
              quietly translating code-switched speech into English, which is invisible to
              a length check because the English is just as long
  figures     every distinct number in the input that survives into the output -- this is a
              corpus about money, and a rewrite that reads well while losing "57 juta" is
              worse than one that reads badly
  labels      speaker labels present, and any the model invented (Host, Interviewer)

RUN AT LEAST THREE SEGMENTS. On ep62 segment 26 Sonnet kept 24 figures of 24; on segment 10
it kept 17, while a model an eighth of its size kept all 24 on both. A single segment would
have recommended the wrong model, in either direction.

THE PROMPT IS THE REPO'S OWN, plus a list of the episode's confirmed spellings, so the name
check happens while the text is being written rather than as a correction pass afterwards.

  python scripts/segment_episode.py ep62 --raw <transcript> --out data/_ep62_segments.json
  python scripts/rewrite_bakeoff.py data/_ep62_segments.json 26
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform == "win32":
    import winreg
    for _name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY", "NVIDIA_API_KEY", "MOONSHOT_API_KEY",
                 "ORCAROUTER_API_KEY"):
        if _name not in os.environ:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as _k:
                    os.environ[_name] = winreg.QueryValueEx(_k, _name)[0]
            except FileNotFoundError:
                pass

import requests  # noqa: E402

from lib_gemini import CLEAN_PROMPT_TEMPLATE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "data" / "_bakeoff"
SYSTEM = "You are a precise text-processing tool. Return only the requested text."
DISALLOWED = ("Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Task,TodoWrite,NotebookEdit,"
              "BashOutput,KillBash")
# Counted in the input and in the output; the rewrite prompt sets 80% as its own floor.
MALAY = ["yang", "tak", "kan", "ni", "tu", "lah", "dia", "kita", "sebab", "macam", "dengan",
         "untuk", "boleh", "kalau", "je", "pun"]

# Model ids rot fast. Checked 2026-09-08: gemini-2.0/2.5-flash 404 for this key,
# nvidia/meta llama-3.3-70b is retired, openrouter's free deepseek slug is gone, and Azure
# Foundry text models need a DEPLOYMENT created in the portal (the Speech key alone returns
# DeploymentNotFound), which is why no Azure arm is listed here.
ARMS = {
    "claude-sonnet-5": ("claude", "claude-sonnet-5"),
    "gemini-3.5-flash": ("gemini", "gemini-3.5-flash"),
    "gemini-flash-lite-latest": ("gemini", "gemini-flash-lite-latest"),
    "nemotron-3.5-lightning:free": ("openrouter", "nvidia/nemotron-3.5-lightning:free"),
    # Free arms, listed 2026-09-17. OpenRouter's free tier trains on the prompt, which is
    # acceptable here only because these transcripts are already published. There is still
    # no free DeepSeek slug. `stealth/union-alpha` is free but carries no `:free` suffix.
    "union-alpha": ("openrouter", "stealth/union-alpha"),
    "nemotron-3-ultra-550b:free": ("openrouter", "nvidia/nemotron-3-ultra-550b-a55b:free"),
    "inkling:free": ("openrouter", "thinkingmachines/inkling:free"),
    "glm-5.2:free": ("openrouter", "z-ai/glm-5.2:free"),
    "dots-3-note:free": ("openrouter", "dots-studio/dots-3-note-preview:free"),
}


def call_claude(model, prompt):
    proc = subprocess.run(
        ["claude", "-p", "--output-format", "json", "--model", model,
         "--disallowedTools", DISALLOWED, "--system-prompt", SYSTEM],
        input=prompt.encode("utf-8"), capture_output=True, timeout=900)
    if proc.returncode:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:300])
    payload = json.loads(proc.stdout.decode("utf-8"))
    if isinstance(payload, list):
        payload = next(e for e in payload if e.get("type") == "result")
    return payload["result"]


def call_gemini(model, prompt):
    # The free tier's per-minute cap (5 req/min, measured 2026-09-18 on gemini-3.6-flash and
    # gemini-3.8-flash alike) is real and routine, not an outage -- a single segment call from
    # a script with no other traffic can trip it. The 429 body names its own retryDelay, so
    # honour that instead of a guess; 3 attempts covers the free-tier window resetting once.
    for attempt in range(3):
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": 32768, "temperature": 0.3}},
            timeout=900)
        if r.status_code == 429 and attempt < 2:
            delay = 10.0
            try:
                for d in r.json()["error"]["details"]:
                    if d.get("@type", "").endswith("RetryInfo"):
                        delay = float(d["retryDelay"].rstrip("s"))
            except Exception:
                pass
            time.sleep(delay + 1)
            continue
        if r.status_code == 503 and attempt < 2:
            # "currently experiencing high demand" -- no retryDelay in the body, unlike 429.
            time.sleep(20)
            continue
        break
    if r.status_code >= 300:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
    candidate = r.json()["candidates"][0]
    parts = candidate.get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError(f"no parts, finishReason={candidate.get('finishReason')}")
    return "".join(p.get("text", "") for p in parts)


def call_openrouter(model, prompt):
    # Free-tier model providers behind OpenRouter 429 routinely under load (measured
    # 2026-09-18 on z-ai/glm-5.2:free: 2 of 6 calls), and OpenRouter gives no retryDelay
    # in the body the way Gemini does, so this waits a fixed interval instead.
    for attempt in range(3):
        r = requests.post("https://openrouter.ai/api/v1/chat/completions",
                          headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
                                   "Content-Type": "application/json"},
                          json={"model": model, "temperature": 0.3,
                                "messages": [{"role": "system", "content": SYSTEM},
                                             {"role": "user", "content": prompt}]},
                          timeout=900)
        if r.status_code == 429 and attempt < 2:
            time.sleep(20)
            continue
        break
    if r.status_code >= 300:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
    message = r.json()["choices"][0]["message"]
    text = message.get("content") or ""
    if not text.strip():
        raise RuntimeError(f"empty content, keys={sorted(message)}")
    return text


def call_nvidia(model, prompt):
    """NVIDIA's own NIM catalog (integrate.api.nvidia.com), not OpenRouter's nvidia/ slugs --
    a different endpoint, so a different rate-limit pool and possibly a different model
    version. Same OpenAI-compatible chat completions shape as OpenRouter."""
    r = requests.post("https://integrate.api.nvidia.com/v1/chat/completions",
                      headers={"Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}",
                               "Content-Type": "application/json"},
                      json={"model": model, "temperature": 0.3,
                            "messages": [{"role": "system", "content": SYSTEM},
                                         {"role": "user", "content": prompt}]},
                      timeout=900)
    if r.status_code >= 300:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
    message = r.json()["choices"][0]["message"]
    text = message.get("content") or ""
    if not text.strip():
        raise RuntimeError(f"empty content, keys={sorted(message)}")
    return text


def call_moonshot(model, prompt):
    """Moonshot AI's Kimi models. api.moonshot.ai (international), not .cn -- the .cn host
    401s on this key, confirmed 2026-09-18."""
    r = requests.post("https://api.moonshot.ai/v1/chat/completions",
                      headers={"Authorization": f"Bearer {os.environ['MOONSHOT_API_KEY']}",
                               "Content-Type": "application/json"},
                      json={"model": model, "temperature": 0.3,
                            "messages": [{"role": "system", "content": SYSTEM},
                                         {"role": "user", "content": prompt}]},
                      timeout=900)
    if r.status_code >= 300:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
    message = r.json()["choices"][0]["message"]
    text = message.get("content") or ""
    if not text.strip():
        raise RuntimeError(f"empty content, keys={sorted(message)}")
    return text


def call_orcarouter(model, prompt):
    """OrcaRouter, an LLM gateway distinct from OpenRouter. orcarouter/free's free tier
    gates on an aged GitHub account linked in the account's profile (confirmed 2026-09-18:
    401/429 before linking, works after); it auto-routes to whichever model it picks that
    moment (seen: deepseek-v4-flash-ga)."""
    r = requests.post("https://api.orcarouter.ai/v1/chat/completions",
                      headers={"Authorization": f"Bearer {os.environ['ORCAROUTER_API_KEY']}",
                               "Content-Type": "application/json"},
                      json={"model": model, "temperature": 0.3,
                            "messages": [{"role": "system", "content": SYSTEM},
                                         {"role": "user", "content": prompt}]},
                      timeout=900)
    if r.status_code >= 300:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:200]}")
    message = r.json()["choices"][0]["message"]
    text = message.get("content") or ""
    if not text.strip():
        raise RuntimeError(f"empty content, keys={sorted(message)}")
    return text


CALLERS = {"claude": call_claude, "gemini": call_gemini, "openrouter": call_openrouter,
          "nvidia": call_nvidia, "moonshot": call_moonshot, "orcarouter": call_orcarouter}


def names_for(video_id):
    """Confirmed spellings, taken from the reviewed correction map so the two never drift."""
    import fix_proper_nouns as F
    names = ["Rafizi Ramli", "Haziq", "Farhan (Pa'an)"]
    for _, replacement, _ in F.CORRECTIONS:
        parts = replacement.split()
        if parts and all(p[:1].isupper() or p[:1].isdigit() for p in parts):
            names.append(replacement)
    return list(dict.fromkeys(names))


def measure(source, text, names):
    body = re.sub(r"^\[[\d:]+\]\s*", "", source, flags=re.M)

    def malay(t):
        words = re.findall(r"[a-z']+", t.lower())
        return sum(1 for w in words if w in MALAY)

    labels = set(re.findall(r"\*\*([^*:]{1,40}):\*\*", text))
    source_labels = set(re.findall(r"^\[[\d:]+\]\s*([^:\n]{1,40}):", source, re.M))
    figures_in = set(re.findall(r"\d[\d.,]*", body))
    figures_out = set(re.findall(r"\d[\d.,]*", text))
    return {
        "char_ratio": round(len(text) / max(1, len(body)), 3),
        "malay_ratio": round(malay(text) / max(1, malay(body)), 3),
        "figures_kept": len(figures_in & figures_out),
        "figures_total": len(figures_in),
        "figures_missing": sorted(figures_in - figures_out)[:10],
        "labels": sorted(labels),
        "invented_labels": sorted(labels - source_labels),
        "missing_labels": sorted(source_labels - labels),
        "names_dropped": [n for n in names
                          if n.lower() in body.lower() and n.lower() not in text.lower()],
        "timestamps_left": len(re.findall(r"\[\d+:\d+", text)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("segments", help="json from segment_episode.py --out")
    ap.add_argument("index", type=int, nargs="+", help="segment index/indices to run")
    ap.add_argument("--arms", nargs="*", default=list(ARMS), choices=list(ARMS))
    ap.add_argument("--video-id", default="0M5hweswMpE")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    segments = json.loads(Path(args.segments).read_text(encoding="utf-8"))
    names = names_for(args.video_id)

    for index in args.index:
        seg = segments[index]
        prompt = (CLEAN_PROMPT_TEMPLATE.format(raw_text=seg["text"])
                  + "\n\nSpellings confirmed for this episode -- use these exact forms and "
                    "never split one name across two spellings:\n"
                  + "\n".join(f"- {n}" for n in names))
        print(f"\nsegment {index}: {seg['title']}")
        print(f"  {seg['turns']} turns, {seg['words']} words, speakers {seg['speakers']}")
        rows = []
        for arm in args.arms:
            kind, model = ARMS[arm]
            began = time.time()
            try:
                text = CALLERS[kind](model, prompt)
                if not text.strip():
                    raise RuntimeError("returned nothing")
            except Exception as exc:
                print(f"  {arm:32} FAILED  {str(exc)[:110]}")
                continue
            row = {"arm": arm, "seconds": round(time.time() - began, 1),
                   **measure(seg["text"], text, names)}
            rows.append(row)
            (OUT_DIR / f"seg{index}_{arm.replace('/', '_').replace(':', '-')}.md").write_text(
                text, encoding="utf-8")
            print(f"  {arm:32} {row['seconds']:6.1f}s  len {row['char_ratio']:.2f}  "
                  f"malay {row['malay_ratio']:.2f}  "
                  f"figures {row['figures_kept']}/{row['figures_total']}  "
                  f"labels {len(row['labels'])}")
            for key in ("invented_labels", "missing_labels", "names_dropped"):
                if row[key]:
                    print(f"       {key}: {row[key]}")
        (OUT_DIR / f"seg{index}_results.json").write_text(
            json.dumps({"segment": {k: v for k, v in seg.items() if k != "text"},
                        "results": rows}, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
