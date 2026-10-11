"""detect_whisper_loops.py must remove what ep67's owner removed and keep what the owner kept.

No audio and no network: `speech` is a stub that returns a fixed fraction, so each case isolates
one rule. The cases are the ep67 facts the rules were built on.

  python scripts/test_whisper_loops.py
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import detect_whisper_loops as D  # noqa: E402


def words(texts, start=0.0, step=0.3, dur=0.25):
    """A word list the way load_words returns it, one word per entry."""
    return [(start + i * step, start + i * step + dur, D.norm(t), t, (0, 0, i)) for i, t in enumerate(texts)]


def run(texts, speech=None, **kw):
    w = words(texts, **kw)
    items, remove = D.detect(w, (lambda a, b: speech) if speech is not None else None)
    return items, remove


def check(name, ok):
    print(("ok    " if ok else "FAIL  ") + name)
    return ok


def main():
    results = []

    # Sari kata oleh x30 over silence: removed, every copy
    items, remove = run(["Sari", "kata", "oleh"] * 30, speech=0.0, step=0.005, dur=0.004)
    results.append(check("silent phrase loop is removed whole", len(remove) == 90 and items[0]["action"] == "removed"))

    # ada x444 over real speech but at 43 words per second: still removed, and it says speech
    items, remove = run(["ada"] * 444, speech=0.83, step=0.023, dur=0.02)
    results.append(check("impossible speech rate is removed even over speech", len(remove) == 444 and items[0]["speech"] == 0.83))

    # ya x10 at 3 words per second over speech: a stutter, flagged and kept
    items, remove = run(["ya"] * 10, speech=0.9, step=0.33, dur=0.3)
    results.append(check("ten normal-speed repeats over speech are kept", not remove and items[0]["action"] == "flagged"))

    # the same 10 with no audio at all: kept, because only the intrinsic rules run
    items, remove = run(["ya"] * 10, speech=None, step=0.33, dur=0.3)
    results.append(check("without audio a 10-repeat run at normal speed is kept", not remove))

    # 25 repeats need no second witness
    items, remove = run(["lah"] * 25, speech=None, step=0.4, dur=0.3)
    results.append(check("25 repeats are removed without audio", len(remove) == 25))

    # how much they are going to get x4: the speaker said it twice, so it is only flagged
    items, remove = run("how much they are going to get".split() * 4, speech=0.73, step=0.35, dur=0.3)
    results.append(check("a 4-repeat phrase is flagged, never removed", not remove and items[0]["kind"] == "weak"))

    # ada ada ada: ordinary Malay
    items, remove = run(["ada", "ada", "ada", "ada"])
    results.append(check("four single-word repeats are not even a candidate", not items and not remove))

    # RM70,000,... inside one token
    token = "RM70" + ",000" * 216
    items, remove = run(["dan", token, "bilion"], speech=0.99)
    results.append(check("a block repeated 216 times inside one token is removed", remove == {1} and items[0]["kind"] == "loop"))

    # laughter is not a loop
    items, remove = run(["hahahahahahahahahahahaha"])
    results.append(check("laughter inside one token is left alone", not items and not remove))

    # a credit line over speech is flagged, over silence removed
    credit = "Terima kasih kerana menonton".split()
    items, remove = run(["bagi", "duit"] + credit + ["dia", "cakap"], speech=0.75)
    results.append(check("a credit line over speech is flagged and kept", not remove and items[0]["action"] == "flagged"))
    items, remove = run(["bagi", "duit"] + credit + ["dia", "cakap"], speech=0.02)
    results.append(check("a credit line over silence is removed", len(remove) == 4 and items[0]["action"] == "removed"))
    items, remove = run(["bagi", "duit"] + credit + ["dia", "cakap"], speech=None)
    results.append(check("a credit line with no audio is never removed", not remove))

    # a loop that contains the credit phrase is counted once, as a loop
    items, remove = run(credit * 30, speech=0.0, step=0.005, dur=0.004)
    results.append(check("a credit phrase inside a removed loop is not listed twice", len(items) == 1))

    # apply_removals rewrites phrases and text, keeps a backup, and is repeatable
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        phrases = [{"offsetMilliseconds": 0, "durationMilliseconds": 5000, "text": "dan " + "ada " * 30 + "bilion",
                    "words": [{"text": t, "offsetMilliseconds": i * 100, "durationMilliseconds": 3}
                              for i, t in enumerate(["dan"] + ["ada"] * 30 + ["bilion"])]},
                   {"offsetMilliseconds": 6000, "durationMilliseconds": 500, "text": "baik",
                    "words": [{"text": "baik", "offsetMilliseconds": 6000, "durationMilliseconds": 400}]}]
        f = tmp / "mai_response_00.json"
        f.write_text(json.dumps({"_chunk_start_s": 0.0, "phrases": phrases}), encoding="utf-8")
        for _ in range(2):
            files, docs, w = D.load_words(tmp)
            items, remove = D.detect(w, lambda a, b: 0.0)
            D.apply_removals(files, docs, w, remove, tmp)
        out = json.loads(f.read_text(encoding="utf-8"))
        ok = (out["phrases"][0]["text"] == "dan bilion" and out["phrases"][1]["text"] == "baik"
              and (tmp / "loops_backup" / f.name).exists()
              and len(json.loads((tmp / "loops_backup" / f.name).read_text(encoding="utf-8"))["phrases"][0]["words"]) == 32)
        results.append(check("--write rewrites the phrase, keeps the original, and a second run changes nothing", ok))

    # the loop stops part-way through a repeat: the partial repeat goes too, and only the tail
    items, remove = run(["dan"] + ["Sari", "kata", "oleh"] * 30 + ["Sari", "kata", "Kerajaan", "berjaya"],
                        speech=0.0, step=0.005, dur=0.004)
    results.append(check("the part-repeat after a removed loop is removed with it",
                         len(remove) == 92 and items[0]["partial_words"] == 2 and 93 not in remove and 94 not in remove))
    items, remove = run(["dan"] + ["Sari", "kata", "oleh"] * 30 + ["Kerajaan"], speech=0.0, step=0.005, dur=0.004)
    results.append(check("no part-repeat, nothing extra removed", len(remove) == 90 and items[0]["partial_words"] == 0))
    items, remove = run(["oleh"] + ["Sari", "kata", "oleh"] * 30, speech=0.0, step=0.005, dur=0.004)
    left = [w[3] for i, w in enumerate(words(["oleh"] + ["Sari", "kata", "oleh"] * 30)) if i not in remove]
    results.append(check("a word before the loop is never taken: one `oleh` is left", len(remove) == 90 and left == ["oleh"]))

    # a laugh run over silence is flagged, and removed only when nobody can laugh that fast
    items, remove = run(["ha"] * 12, speech=0.05, step=0.33, dur=0.3)
    results.append(check("a slow laugh run over silence is flagged, not removed", not remove and items[0]["action"] == "flagged"))
    items, remove = run(["ha"] * 12, speech=0.05, step=0.05, dur=0.04)
    results.append(check("a laugh run at 20 words per second is removed", len(remove) == 12))

    # phrase times follow the words that are left; an untouched phrase is not changed
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        def ph(off, texts):
            ws = [{"text": t, "offsetMilliseconds": off + i * 20, "durationMilliseconds": 10} for i, t in enumerate(texts)]
            return {"offsetMilliseconds": off, "durationMilliseconds": 9000, "text": " ".join(texts), "words": ws}
        keep = ph(60000, ["selamat", "pagi"])
        (tmp / "mai_response_00.json").write_text(json.dumps({"_chunk_start_s": 0.0, "phrases": [
            ph(10000, ["kata"] * 40 + ["Kerajaan", "berjaya"]), keep]}), encoding="utf-8")
        files, docs, w = D.load_words(tmp)
        items, remove = D.detect(w, lambda a, b: 0.0)
        D.apply_removals(files, docs, w, remove, tmp)
        out = json.loads((tmp / "mai_response_00.json").read_text(encoding="utf-8"))["phrases"]
        results.append(check("a phrase starts at its first remaining word, an untouched one is unchanged",
                             out[0]["offsetMilliseconds"] == 10000 + 40 * 20 and out[0]["durationMilliseconds"] == 30
                             and out[1] == keep))

    # a fresh ASR run into the same folder: the old backup is stale and is never read
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        def put(texts):
            ws = [{"text": t, "offsetMilliseconds": i * 100, "durationMilliseconds": 3} for i, t in enumerate(texts)]
            (tmp / "mai_response_00.json").write_text(json.dumps({"_chunk_start_s": 0.0, "phrases": [
                {"offsetMilliseconds": 0, "durationMilliseconds": 9000, "text": " ".join(texts), "words": ws}]}), encoding="utf-8")
        put(["dan"] + ["ada"] * 30 + ["bilion"])
        files, docs, w = D.load_words(tmp)
        D.apply_removals(files, docs, w, D.detect(w, lambda a, b: 0.0)[1], tmp)
        results.append(check("after --write the backup is the one in use", D.backup_is_ours(tmp)))
        put(["baru", "episod", "lain"] + ["ya"] * 30 + ["habis"])           # Whisper re-run, new words
        results.append(check("a re-run of ASR makes the old backup stale", not D.backup_is_ours(tmp)))
        files, docs, w = D.load_words(tmp)
        results.append(check("the stale backup is not read", [x[3] for x in w][:3] == ["baru", "episod", "lain"]))
        D.apply_removals(files, docs, w, D.detect(w, lambda a, b: 0.0)[1], tmp)
        kept = json.loads((tmp / "loops_backup" / "mai_response_00.json").read_text(encoding="utf-8"))
        results.append(check("--write then replaces the stale backup with the new originals",
                             kept["phrases"][0]["text"].startswith("baru episod lain") and D.backup_is_ours(tmp)))

    failed = results.count(False)
    print(f"\n{len(results) - failed} of {len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
