"""Score Azure MAI-Transcribe-2 on the Revolab Malaysian ASR benchmark.

WHY NOT THEIR run_eval.py. Their loader decodes audio through `datasets` 5, which decodes
through torchcodec, which needs FFmpeg's shared libraries. The FFmpeg on this machine is a
static build with no DLLs beside it, so torchcodec cannot load. Rather than install a second
FFmpeg, this reads the parquet directly with pyarrow and posts the stored audio bytes
untouched -- which also avoids a decode-and-re-encode round trip that their path performs and
this one does not.

THE SCORING IS THEIRS, DELIBERATELY. A number is only worth having if it sits on the same
yardstick as the fourteen models already on their leaderboard, so this reproduces
`asr_benchmark/runner.py` exactly: both references normalized with the Malay normalizer, both
aligned against the prediction per row, and the reference giving the LOWER error rate kept
(ties going to the dataset's own normalized text). Corpus WER is total errors over total
reference length, not a mean of per-row rates. Their `_align` is imported from the checkout
rather than reimplemented -- a reimplementation would only prove my arithmetic matches itself.

TRANSCRIBE STYLE IS THE EXPERIMENT. This pipeline runs `verbatim`, which keeps fillers.
A benchmark reference that omits them charges every filler as an insertion, so `verbatim`
will score worse than `clean` while being the setting actually in production. Run both. The
gap is the cost of the production setting, and reporting only `clean` would flatter the
engine relative to how this repo uses it.

  python scripts/revolab_run_mai.py --style verbatim
  python scripts/revolab_run_mai.py --style clean
"""
import argparse
import importlib.util
import io
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform == "win32":
    import winreg
    for _n in ("AZURE_SPEECH_KEY", "AZURE_SPEECH_REGION", "AZURE_SPEECH_ENDPOINT"):
        if _n not in os.environ:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as _k:
                    os.environ[_n] = winreg.QueryValueEx(_k, _n)[0]
            except FileNotFoundError:
                pass

import pyarrow.parquet as pq  # noqa: E402
import requests  # noqa: E402

from vendor.revolab_normalizer import MalayTextNormalizer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PARQUET = ROOT / "data" / "_revolab_data" / "public.parquet"
HARNESS_METRICS = ROOT / "data" / "_revolab" / "asr_benchmark" / "utils" / "metrics.py"
API_VERSION = "2025-10-15"
MODEL = "MAI-Transcribe-2"
RETRY_STATUS = (429, 500, 502, 503, 504)


def load_align():
    """Import the harness's aligner without importing its package (which pulls torch)."""
    if not HARNESS_METRICS.exists():
        sys.exit(f"{HARNESS_METRICS} not found -- clone the MIT harness into data/_revolab:\n"
                 f"  git clone https://github.com/Revolab-Sdn-Bhd/revolab-asr-benchmark "
                 f"data/_revolab")
    spec = importlib.util.spec_from_file_location("_revolab_metrics", HARNESS_METRICS)
    module = importlib.util.module_from_spec(spec)
    # @dataclass resolves annotations through sys.modules[cls.__module__], so the module has
    # to be registered before its body runs or the decorator raises on a None lookup.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module._align


def endpoint():
    host = os.environ.get("AZURE_SPEECH_ENDPOINT")
    if not host:
        region = os.environ.get("AZURE_SPEECH_REGION")
        if not region:
            sys.exit("set AZURE_SPEECH_ENDPOINT or AZURE_SPEECH_REGION")
        host = f"https://{region}.api.cognitive.microsoft.com"
    return f"{host.rstrip('/')}/speechtotext/transcriptions:transcribe?api-version={API_VERSION}"


def text_of(payload):
    combined = payload.get("combinedPhrases")
    if isinstance(combined, list) and combined:
        text = " ".join(c.get("text", "") for c in combined).strip()
        if text:
            return text
    for key in ("phrases", "segments", "results"):
        items = payload.get(key)
        if isinstance(items, list) and items:
            return " ".join(i.get("text", "") for i in items).strip()
    return str(payload.get("text", "")).strip()


def transcribe(audio_bytes, name, style, url, key, retries=4):
    definition = {
        "enhancedMode": {"enabled": True, "model": MODEL,
                         "modelOptions": {"transcribeStyle": style}},
        "diarization": {"enabled": False},
    }
    last = None
    for attempt in range(retries):
        response = requests.post(
            url, headers={"Ocp-Apim-Subscription-Key": key},
            files={"audio": (name, io.BytesIO(audio_bytes), "audio/wav")},
            data={"definition": json.dumps(definition)}, timeout=600)
        if response.status_code < 300:
            return text_of(response.json()), None
        last = f"HTTP {response.status_code} {response.text[:140]}"
        if response.status_code not in RETRY_STATUS or attempt == retries - 1:
            break
        time.sleep(5 * (attempt + 1))
    return "", last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", default="verbatim", choices=["verbatim", "clean"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel requests; RTFx is meaningless above 1")
    args = ap.parse_args()

    key = os.environ.get("AZURE_SPEECH_KEY")
    if not key:
        sys.exit("set AZURE_SPEECH_KEY")
    if not PARQUET.exists():
        sys.exit(f"{PARQUET} not found -- download the gated split first")

    align = load_align()
    normalize = MalayTextNormalizer()
    url = endpoint()

    table = pq.read_table(PARQUET)
    rows = table.to_pylist()
    if args.limit:
        rows = rows[:args.limit]

    cache_path = ROOT / "data" / f"_revolab_mai_{args.style}.jsonl"
    done = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done[r["id"]] = r
    print(f"{len(rows)} clips, style={args.style}, {len(done)} already cached", flush=True)

    todo = [r for r in rows if r["id"] not in done]
    if todo:
        began = time.time()
        lock_file = cache_path.open("a", encoding="utf-8")

        def run(row):
            text, err = transcribe(row["audio"]["bytes"],
                                   row["audio"].get("path") or f"{row['id']}.wav",
                                   args.style, url, key)
            return {"id": row["id"], "prediction": text, "error": err}

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for n, rec in enumerate(pool.map(run, todo), 1):
                done[rec["id"]] = rec
                lock_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
                lock_file.flush()
                if n % 25 == 0 or n == len(todo):
                    rate = n / max(1e-9, time.time() - began)
                    print(f"  {n}/{len(todo)}  {rate*60:.0f} clips/min", flush=True)
        lock_file.close()

    failed = [r for r in done.values() if r.get("error")]
    totals, by_cat = {"h": 0, "s": 0, "i": 0, "d": 0}, {}
    scored = 0
    for row in rows:
        rec = done.get(row["id"])
        if not rec or rec.get("error"):
            continue
        pred = normalize(rec["prediction"])
        cands = [normalize(row["text"])]
        if row.get("normalized_text"):
            cands.append(normalize(row["normalized_text"]))
        best, best_wer = None, None
        # Their rule: the dataset's own normalized reference wins ties, so evaluate it last.
        for ref in cands:
            st = align(ref.split(), pred.split())
            wer = st.errors / max(st.ref_length, 1)
            if best_wer is None or wer <= best_wer:
                best, best_wer = st, wer
        totals["h"] += best.hits; totals["s"] += best.substitutions
        totals["i"] += best.insertions; totals["d"] += best.deletions
        cat = by_cat.setdefault(row["category"], {"h": 0, "s": 0, "i": 0, "d": 0, "n": 0})
        cat["h"] += best.hits; cat["s"] += best.substitutions
        cat["i"] += best.insertions; cat["d"] += best.deletions; cat["n"] += 1
        scored += 1

    def wer(c):
        ref = c["h"] + c["s"] + c["d"]
        return (c["s"] + c["i"] + c["d"]) / max(ref, 1)

    print(f"\nMAI-Transcribe-2  style={args.style}  scored {scored}/{len(rows)}"
          f"{f', {len(failed)} failed' if failed else ''}")
    print(f"  OVERALL WER {wer(totals):.2%}   "
          f"sub {totals['s']/max(1,totals['h']+totals['s']+totals['d']):.2%} "
          f"ins {totals['i']/max(1,totals['h']+totals['s']+totals['d']):.2%} "
          f"del {totals['d']/max(1,totals['h']+totals['s']+totals['d']):.2%}")
    print(f"\n  {'category':22} {'n':>4} {'WER':>8}")
    for name, c in sorted(by_cat.items(), key=lambda kv: -wer(kv[1])):
        print(f"  {name:22} {c['n']:>4} {wer(c):>7.2%}")
    if failed:
        print(f"\n  {len(failed)} failed, first: {failed[0]['error'][:120]}")


if __name__ == "__main__":
    main()
