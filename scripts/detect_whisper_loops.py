"""Find Whisper's repetition loops and its invented credit lines, test them against the AUDIO.

WHY. ep67 was the first episode on local Whisper-large-v3-turbo. Against the owner's corrected
copy its tail scored 17.4% word error, against 5.1% in the part the owner edited directly. Three
loops make up 928 of the 954 words the owner removed in long spans: `Sari kata oleh` x88, `ada`
x444 and `RM70,000,000,000,...` (216 repeats of `,000` inside ONE token). Whisper also wrote
`Terima kasih kerana menonton` five times, each over real speech.

THE YOUTUBE CAPTION IS NOT THE WITNESS. Its absence of a word is no reason to delete one: in
the same episode the caption lacked 13 of the 16 runs of three or more words that the owner
restored by ear. So this reads the audio. A loop is removed only when the audio or the speech
rate says nobody said it; everything else is flagged with a `?t=` link and left in.

THE RULE, with the ep67 numbers it was built on:

  strong loop    the same 1 to 8 words repeated 10 or more times in a row, AND one of: faster
                 than 7 words per second (nobody speaks that fast; `ada` x444 ran at 43 w/s,
                 `Sari kata oleh` at 528), or Silero reports under 20% speech over the span,
                 or 25 or more repeats. A block of 2 to 8 characters repeated 25 or more times
                 inside one token is the same thing (`,000` x216). REMOVED, all copies. A run of
                 laughter (`ha ha ha`) never counts as silence: Silero can score a real laugh low.
  weak loop      4 to 9 repeats (6 to 9 for a single word, because `ada ada` is ordinary
                 Malay). FLAGGED, kept. ep67 18:22 had `how much they are going to get` x4
                 where the speaker said it twice, so deleting a short run deletes real speech.
  credit line    `Terima kasih kerana menonton` and its relatives. REMOVED only where the audio
                 is silent (under 10% speech). All five in ep67 had 26% to 86% speech under
                 them, so they are FLAGGED: Whisper wrote a closing credit over real words.

A removed loop over real speech (`ada` x444 had 83% speech) leaves a gap, and the report says
so: the words the speaker really said are not in the text and need the owner's ear.

  python scripts/detect_whisper_loops.py ep67             # dry run, prints the report
  python scripts/detect_whisper_loops.py ep67 --write     # rewrites the responses in place

--write keeps the untouched responses in `<words dir>/loops_backup/` and reads from there while
they still match what --write left in the folder, so a second run gives the same result. A fresh
ASR run into the same folder changes the files, the backup is then stale, and it is replaced.

A removed loop also takes the part-repeat it stops in (`Sari kata` after 88 x `Sari kata oleh`). Run it BEFORE `mai_words_from_responses.py`,
which builds `mai_words.json` from these files; nightly_recut.py does. CPU only: the GPU is the
camera pass's.
"""
import argparse
import bisect
import glob
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

os.environ["CUDA_VISIBLE_DEVICES"] = ""        # CPU only: never a second GPU process

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

MIN_REPEATS = 4            # a phrase repeated this often is a candidate
SINGLE_WORD_MIN = 6        # `ada ada ada` is ordinary Malay
STRONG_REPEATS = 10
SURE_REPEATS = 25          # this many repeats needs no second witness
MAX_N = 8                  # longest repeated phrase, in words
IMPOSSIBLE_WPS = 7.0       # words per second that nobody reaches
SILENT = 0.20              # speech fraction below this over a loop: nobody was talking
CREDIT_SILENT = 0.10       # a credit line is removed only over this much silence
TOKEN_MIN = 6              # a block repeated this often inside one token is a candidate
LAUGH = re.compile(r"^(?:ha|he|hi|ho|hu|hm|mm|ah|oh)+$", re.I)
INTRA = re.compile(r"(.{2,8}?)\1{5,}")
CREDITS = [["terima", "kasih", "kerana", "menonton"], ["terima", "kasih", "atas", "tontonan"],
           ["subtitle", "by"], ["subtitles", "by"], ["sari", "kata", "oleh"]]
SR = 16000


def norm(w):
    return re.sub(r"[^\w']", "", w.lower())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def backup_is_ours(base):
    """True when `loops_backup/` holds the originals of the responses now in `base`.

    --write records the hash of each file it rewrites in `loops_backup/written.json`. A fresh
    Whisper run into the same folder changes those hashes, and the old backup is then stale:
    reading it would put the previous run's words over the new ones.
    """
    rec = Path(base) / "loops_backup" / "written.json"
    if not rec.is_file():
        return False
    written = json.loads(rec.read_text(encoding="utf-8"))
    now = {f.name: sha(f) for f in Path(base).glob("mai_response_*.json")}
    return bool(written) and now == written


def load_words(words_dir):
    """Every word of every response, in time order, with where it lives.

    A word is (t0, t1, normalised, raw, (file, phrase, word)). Reads `loops_backup/` when it
    holds the originals of what is in the folder, so a repeat run starts from the untouched
    responses.
    """
    base = Path(words_dir)
    src = base / "loops_backup" if backup_is_ours(base) else base
    files = sorted(src.glob("mai_response_*.json"))
    docs = [json.loads(f.read_text(encoding="utf-8")) for f in files]
    words = []
    for fi, doc in enumerate(docs):
        start = float(doc.get("_chunk_start_s", 0.0))
        for pi, ph in enumerate(doc["phrases"]):
            for wi, w in enumerate(ph.get("words", [])):
                t0 = start + w["offsetMilliseconds"] / 1000.0
                t1 = t0 + w["durationMilliseconds"] / 1000.0
                words.append((t0, t1, norm(w["text"]), w["text"], (fi, pi, wi)))
    words.sort(key=lambda x: x[0])
    return files, docs, words


def find_phrase_runs(toks):
    """Maximal back-to-back repeats of a 1 to 8 word phrase: [(i0, i1, k, n)]."""
    runs, i, total = [], 0, len(toks)
    while i < total:
        best = None
        for n in range(1, MAX_N + 1):
            if i + 2 * n > total:
                break
            gram, k = toks[i:i + n], 1
            while i + (k + 1) * n <= total and toks[i + k * n:i + (k + 1) * n] == gram:
                k += 1
            need = MIN_REPEATS if n > 1 else SINGLE_WORD_MIN
            if k >= need and (best is None or k * n > best[0] * best[1]):
                best = (k, n)
        if best:
            k, n = best
            runs.append((i, i + k * n, k, n))
            i += k * n
        else:
            i += 1
    return runs


def find_token_repeats(raws):
    """A block repeated inside ONE token: [(index, block, k)]. Laughter is not a loop."""
    out = []
    for i, raw in enumerate(raws):
        m = INTRA.search(raw)
        if m and not LAUGH.match(m.group(1)):
            out.append((i, m.group(1), len(m.group(0)) // len(m.group(1))))
    return out


def find_credits(toks):
    out = []
    for ph in CREDITS:
        n = len(ph)
        out += [(j, j + n, " ".join(ph)) for j in range(len(toks) - n + 1) if toks[j:j + n] == ph]
    return sorted(out)


class Audio:
    """Silero speech fraction over a span of the decoded 16 kHz audio."""

    def __init__(self, path):
        import soundfile as sf
        import torch
        from silero_vad import load_silero_vad
        self.torch = torch
        self.samples, sr = sf.read(str(path), dtype="float32")
        if sr != SR:
            sys.exit(f"{path} is {sr} Hz, expected {SR}")
        self.model = load_silero_vad()

    def speech(self, a, b):
        a, b = max(0.0, a), min(len(self.samples) / SR, b)
        n = (int((b - a) * SR) // 512) * 512
        if n < 512:
            return None
        x = self.torch.from_numpy(self.samples[int(a * SR):int(a * SR) + n])
        self.model.reset_states()
        probs = [float(self.model(x[j:j + 512], SR)) for j in range(0, n, 512)]
        return sum(p > 0.5 for p in probs) / len(probs)


def detect(words, speech):
    """Classify every candidate. `speech(a, b)` returns a 0..1 fraction or None.

    Returns (items, remove) where remove is the set of indices into `words` to delete.
    """
    toks = [w[2] for w in words]
    items, remove = [], set()

    def span_speech(a, b):
        return speech(a - 1.0, b + 1.0) if speech else None

    for i0, i1, k, n in find_phrase_runs(toks):
        t0, t1 = words[i0][0], words[i1 - 1][1]
        dur = max(t1 - t0, 0.01)
        rate, sp = (i1 - i0) / dur, span_speech(t0, t1)
        gram = " ".join(toks[i0:i0 + n])
        laugh = all(LAUGH.match(t) for t in toks[i0:i0 + n])   # Silero can score a real laugh as silence
        strong = k >= STRONG_REPEATS and (rate > IMPOSSIBLE_WPS or k >= SURE_REPEATS
                                          or (not laugh and sp is not None and sp < SILENT))
        tail = 0
        if strong:
            # the loop usually stops part-way through a repeat (`Sari kata` after 88 x `Sari kata
            # oleh`, in ep65 and ep67): those words belong to the loop too. One matching word is
            # not enough: `oleh` before 30 x `Sari kata oleh` also reads as 30 x `oleh Sari kata`
            # plus a spare `oleh`, and that spare word may be real speech.
            while tail < n - 1 and i1 + tail < len(toks) and toks[i1 + tail] == toks[i0 + tail]:
                tail += 1
            if tail < 2:
                tail = 0
        items.append({"kind": "loop" if strong else "weak", "t0": t0, "t1": t1, "gram": gram,
                      "repeats": k, "partial_words": tail, "words_per_s": round(rate, 1),
                      "speech": None if sp is None else round(sp, 2),
                      "action": "removed" if strong else "flagged"})
        if strong:
            remove.update(range(i0, i1 + tail))
    for i, block, k in find_token_repeats([w[3] for w in words]):
        t0, t1 = words[i][0], words[i][1]
        sp = span_speech(t0, t1)
        strong = k >= SURE_REPEATS
        items.append({"kind": "loop" if strong else "weak", "t0": t0, "t1": t1,
                      "gram": f"{words[i][3][:24]}... ({block!r} x{k})", "repeats": k,
                      "words_per_s": None, "speech": None if sp is None else round(sp, 2),
                      "action": "removed" if strong else "flagged"})
        if strong:
            remove.add(i)
    for j0, j1, gram in find_credits(toks):
        if j0 in remove:
            continue                       # already inside a removed loop
        t0, t1 = words[j0][0], words[j1 - 1][1]
        sp = span_speech(t0, t1)
        silent = sp is not None and sp < CREDIT_SILENT
        items.append({"kind": "credit", "t0": t0, "t1": t1, "gram": gram, "repeats": 1,
                      "words_per_s": None, "speech": None if sp is None else round(sp, 2),
                      "action": "removed" if silent else "flagged"})
        if silent:
            remove.update(range(j0, j1))
    items.sort(key=lambda x: x["t0"])
    return items, remove


def apply_removals(files, docs, words, remove, base):
    """Rewrite the responses without the removed words. Originals go to loops_backup/."""
    backup = Path(base) / "loops_backup"
    if backup.is_dir() and not backup_is_ours(base):
        shutil.rmtree(backup)              # a fresh ASR run replaced the responses: the backup is stale
    backup.mkdir(exist_ok=True)
    gone = {}
    for idx in remove:
        fi, pi, wi = words[idx][4]
        gone.setdefault((fi, pi), set()).add(wi)
    written = {}
    for fi, f in enumerate(files):
        keep = backup / f.name
        if not keep.exists():
            shutil.copy2(f, keep)
        doc = docs[fi]
        phrases = []
        for pi, ph in enumerate(doc["phrases"]):
            drop = gone.get((fi, pi))
            if drop:
                ph["words"] = [w for wi, w in enumerate(ph["words"]) if wi not in drop]
                if not ph["words"]:
                    continue
                ph["text"] = " ".join(w["text"] for w in ph["words"])
                if "offsetMilliseconds" in ph:     # the phrase spans only the words that are left
                    first, last = ph["words"][0], ph["words"][-1]
                    ph["offsetMilliseconds"] = first["offsetMilliseconds"]
                    ph["durationMilliseconds"] = (last["offsetMilliseconds"] + last["durationMilliseconds"]
                                                  - first["offsetMilliseconds"])
            phrases.append(ph)
        doc["phrases"] = phrases
        out = Path(base) / f.name
        out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        written[f.name] = sha(out)
    (backup / "written.json").write_text(json.dumps(written), encoding="utf-8")


def link(vid, t):
    return f"https://youtu.be/{vid}?t={max(0, int(t) - 5)}"


def stamp(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}"


def find_audio(vid):
    for name in (f"{vid}.vad16k.wav", f"_{vid}.16k.wav"):
        p = ROOT / "audio" / name
        if p.exists():
            return p
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tag", help="episode tag, e.g. ep67")
    ap.add_argument("--words-dir", help="default data/_mai_<video id>")
    ap.add_argument("--audio", help="decoded 16 kHz wav; default audio/<id>.vad16k.wav")
    ap.add_argument("--no-audio", action="store_true", help="intrinsic rules only")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", help="also write the items here")
    a = ap.parse_args()

    from mai_words_from_responses import video_id_for
    vid = video_id_for(a.tag)
    base = Path(a.words_dir) if a.words_dir else ROOT / "data" / f"_mai_{vid}"
    files, docs, words = load_words(base)
    if not files:
        sys.exit(f"no mai_response_*.json under {base}")
    print(f"{a.tag}: {len(words)} words in {len(files)} response file(s) under {base.name}")

    audio = None
    if not a.no_audio:
        wav = Path(a.audio) if a.audio else find_audio(vid)
        if wav and wav.exists():
            audio = Audio(wav)
            print(f"audio: {wav.name}")
        else:
            print("audio: none found, so only the intrinsic rules run (a loop still needs 10 repeats "
                  "and 7 words per second or 25 repeats; a credit line is never removed)")
    items, remove = detect(words, audio.speech if audio else None)

    removed = [x for x in items if x["action"] == "removed"]
    flagged = [x for x in items if x["action"] == "flagged"]
    print(f"\n{len(removed)} removed ({len(remove)} words), {len(flagged)} flagged and kept")
    for x in items:
        sp = "n/a" if x["speech"] is None else f"{x['speech']:.2f}"
        rate = "" if x["words_per_s"] is None else f"{x['words_per_s']} w/s  "
        extra = f"  +{x['partial_words']} partial word(s)" if x.get("partial_words") else ""
        print(f"  {x['action'].upper():8s} {stamp(x['t0'])}  {x['kind']:6s} x{x['repeats']:<4d} "
              f"'{x['gram'][:46]}'{extra}  {rate}speech {sp}\n           {link(vid, x['t0'])}")
    over = [x for x in removed if x["speech"] is not None and x["speech"] >= 0.5]
    if over:
        print(f"\n{len(over)} removed loop(s) sat over real speech. The words the speaker said there "
              "are NOT in the text; listen at the links above and add them.")
    if a.json:
        Path(a.json).write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.write:
        apply_removals(files, docs, words, remove, base)
        (base / "loops.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nrewrote {len(files)} response file(s); originals in {base.name}/loops_backup/")
    else:
        print("\ndry run -- pass --write to apply")


if __name__ == "__main__":
    main()
