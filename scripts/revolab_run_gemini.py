"""Score a current Gemini model on the Revolab Malaysian ASR benchmark.

Mirrors scripts/revolab_run_mai.py exactly (same parquet read, same scoring against the
harness's own `_align` and Malay normalizer), swapping only the transcription call. Built
2026-09-18 to answer whether MAI-Transcribe-2 (3.96% overall / 3.39% podcast WER, measured
2026-09-08, see [[project_asr_engine_measured]]) is still the strongest contender against
whatever Gemini model is live today -- the harness's own gemini_model.py still points at
gemini-2.5-flash/pro, both 404 for this key as of today.

  python scripts/revolab_run_gemini.py --model gemini-flash-lite-latest --limit 100
"""
import argparse
import base64
import importlib.util
import json
import os
import sys
import time
import winreg
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

if sys.platform == "win32":
    for _n in ("GEMINI_API_KEY",):
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
RETRY_STATUS = (429, 500, 502, 503, 504)
PROMPT = ("Transcribe this audio verbatim in the original language(s) spoken, keeping "
         "fillers and disfluencies exactly as said. Return only the transcript, no "
         "commentary, no timestamps, no speaker labels.")


def load_align():
    if not HARNESS_METRICS.exists():
        sys.exit(f"{HARNESS_METRICS} not found -- clone the MIT harness into data/_revolab")
    spec = importlib.util.spec_from_file_location("_revolab_metrics", HARNESS_METRICS)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module._align


def transcribe(audio_bytes, model, retries=4):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {"contents": [{"parts": [
        {"text": PROMPT},
        {"inline_data": {"mime_type": "audio/wav",
                         "data": base64.b64encode(audio_bytes).decode("ascii")}}]}],
              "generationConfig": {"temperature": 0.0}}
    last = None
    for attempt in range(retries):
        r = requests.post(url, headers={"x-goog-api-key": os.environ["GEMINI_API_KEY"]},
                          json=payload, timeout=600)
        if r.status_code < 300:
            try:
                cand = r.json()["candidates"][0]
                parts = cand.get("content", {}).get("parts", [])
                return "".join(p.get("text", "") for p in parts).strip(), None
            except (KeyError, IndexError) as exc:
                return "", f"parse error: {exc} -- {r.text[:140]}"
        last = f"HTTP {r.status_code} {r.text[:140]}"
        if r.status_code == 429:
            time.sleep(15)
        elif r.status_code == 503:
            time.sleep(20)
        elif r.status_code not in RETRY_STATUS or attempt == retries - 1:
            break
    return "", last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-flash-lite-latest")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=1,
                    help="free-tier RPM caps make >1 counterproductive for the newer models")
    args = ap.parse_args()

    if not PARQUET.exists():
        sys.exit(f"{PARQUET} not found -- download the gated split first")

    align = load_align()
    normalize = MalayTextNormalizer()

    table = pq.read_table(PARQUET)
    rows = table.to_pylist()
    if args.limit:
        rows = rows[:args.limit]

    cache_path = ROOT / "data" / f"_revolab_{args.model}.jsonl"
    done = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            done[r["id"]] = r
    print(f"{len(rows)} clips, model={args.model}, {len(done)} already cached", flush=True)

    todo = [r for r in rows if r["id"] not in done]
    if todo:
        began = time.time()
        lock_file = cache_path.open("a", encoding="utf-8")

        def run(row):
            text, err = transcribe(row["audio"]["bytes"], args.model)
            return {"id": row["id"], "prediction": text, "error": err}

        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for n, rec in enumerate(pool.map(run, todo), 1):
                done[rec["id"]] = rec
                lock_file.write(json.dumps(rec, ensure_ascii=False) + "\n")
                lock_file.flush()
                if n % 10 == 0 or n == len(todo):
                    rate = n / max(1e-9, time.time() - began)
                    print(f"  {n}/{len(todo)}  {rate*60:.1f} clips/min", flush=True)
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

    print(f"\n{args.model}  scored {scored}/{len(rows)}"
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
