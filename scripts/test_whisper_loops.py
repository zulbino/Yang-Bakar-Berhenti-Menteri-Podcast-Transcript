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

    failed = results.count(False)
    print(f"\n{len(results) - failed} of {len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
