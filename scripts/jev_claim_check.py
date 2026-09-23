"""Ask Jev whether a rewritten segment kept what each speaker said. Report only; writes nothing.

WHY. The rewrite gate (`rewrite_segments.py`) measures length, Malay density, figures and
shape. None of those can see a changed CLAIM: a rewrite that credits a sentence to the
wrong speaker, invents an opinion, or drops an argument passes all four. Jev (TypeSafe's
decision model) is a cheap judge for exactly that shape of question: tested 2026-09-21, it
scored a genuine rewrite 0.83-0.90 and a reversed claim 0.02-0.03 on "stance kept". It is
weak at counting and numbers, so figures stay with `check_figures.py`.

ONE CALL PER SEGMENT, THREE QUESTIONS. Jev charges for the state once per call, whatever the
number of questions, so the three questions share one request.

--controls runs the same call on five copies of each rewrite damaged on purpose: an
invented sentence, two speakers' labels swapped everywhere, the middle third of the turns
cut, and the small versions of the last two: only the longest turn moved to the other
speaker, and only the longest turn removed.
Each damage has one question that must catch it. Read the separation table before trusting
any score on a real rewrite: a question that does not separate its control from the real
text is not a check.

--published checks the PUBLISHED interview.md instead of the rewrite stage's segment files,
because post-steps such as fix_proper_nouns.py change the text after the rewrite, and most
episodes were rewritten whole, before segments existed. Each printed `match` is how well a
segment's first 15 raw words were found in interview.md; below 0.5 the segment is joined to
the one before rather than cut in the wrong place.

A score at or above FLAG on the real text is a flag for a person to read, never a verdict.

    python scripts/jev_claim_check.py ep01:bakar --controls
    python scripts/jev_claim_check.py ep01:bakar
    python scripts/jev_claim_check.py ep40 --published
"""
import json
import os
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent))
from common import artifact_tag

ROOT = Path(__file__).resolve().parent.parent
URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"  # pinned: jev-latest moves on each release and thresholds do not transfer
# Set from the controls on ep01:bakar, 2026-09-23: no real rewrite scored above 0.35 on any
# question, and no damaged copy scored below 0.75 on its own question.
FLAG = 0.5

QUESTIONS = {
    "invented": {
        "type": "noul",
        "instructions": "SOURCE is a verbatim podcast transcript segment. CANDIDATE is an edited "
                        "version of it. Does CANDIDATE contain a statement, claim or opinion that "
                        "no speaker makes in SOURCE, or reverse what a speaker says in SOURCE?",
        "criteria": {"true": "CANDIDATE adds or reverses a claim",
                     "false": "every claim in CANDIDATE is made in SOURCE by someone"},
    },
    "misattributed": {
        "type": "noul",
        "instructions": "SOURCE is a verbatim podcast transcript segment. CANDIDATE is an edited "
                        "version of it. Each line starts with the speaker's name. Does CANDIDATE "
                        "credit a statement to a different speaker than the one who says it in SOURCE?",
        "criteria": {"true": "a statement is under the wrong speaker's name",
                     "false": "every statement is under the same speaker as in SOURCE"},
    },
    "dropped": {
        "type": "noul",
        "instructions": "SOURCE is a verbatim podcast transcript segment. CANDIDATE is an edited "
                        "version of it. Does CANDIDATE leave out a substantive point (an argument, "
                        "fact, example or name) that SOURCE contains? Removing filler words, "
                        "repetition and false starts does not count.",
        "criteria": {"true": "a substantive point from SOURCE is missing",
                     "false": "every substantive point in SOURCE is in CANDIDATE"},
    },
}
# which question each control must trip
CONTROL_TARGET = {"fabricated": "invented", "swapped": "misattributed", "cut": "dropped",
                  "one_swapped": "misattributed", "one_cut": "dropped"}
INVENTED = ("Saya nak tegaskan, saya sokong penuh cadangan untuk hapuskan semua subsidi "
            "petrol esok juga, tanpa sebarang bantuan tunai kepada rakyat.")


def turns_from_source(text):
    """`[0:01:43] Rafizi: text` -> [("Rafizi", "text"), ...]"""
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        m = re.match(r"\[[\d:]+\]\s*([^:]+):\s*(.*)", block.strip(), re.S)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def turns_from_rewrite(text):
    """`**Rafizi:** text` -> [("Rafizi", "text"), ...]"""
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        m = re.match(r"\*\*([^*]+?):\*\*\s*(.*)", block.strip(), re.S)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip()))
    return out


def render(turns):
    return "\n\n".join(f"{who}: {what}" for who, what in turns)


def fabricated(turns):
    t = list(turns)
    i = len(t) // 2
    t[i] = (t[i][0], t[i][1] + " " + INVENTED)
    return t


def swapped(turns):
    counts = {}
    for who, _ in turns:
        if who != "Speaker ?":
            counts[who] = counts.get(who, 0) + 1
    top = sorted(counts, key=counts.get, reverse=True)[:2]
    if len(top) < 2:
        return None
    a, b = top
    return [(b if who == a else a if who == b else who, what) for who, what in turns]


def one_swapped(turns):
    """The longest turn only, moved under the other main speaker's name."""
    top = swapped(turns)
    if top is None:
        return None
    changed = [k for k in range(len(turns)) if top[k][0] != turns[k][0]]
    i = max(changed, key=lambda k: len(turns[k][1]))
    t = list(turns)
    t[i] = (top[i][0], t[i][1])
    return t


def one_cut(turns):
    """The longest turn removed, and nothing else."""
    if len(turns) < 3:
        return None
    i = max(range(len(turns)), key=lambda k: len(turns[k][1]))
    return turns[:i] + turns[i + 1:]


def cut(turns):
    n = len(turns)
    if n < 3:
        return None
    return turns[: n // 3] + turns[2 * n // 3:]


def ask(state):
    body = {"state": state, "model": MODEL, "questions": QUESTIONS}
    headers = {"Authorization": f"Bearer {os.environ['TYPESAFE_API_KEY']}",
               "Content-Type": "application/json"}
    for attempt in range(4):
        r = requests.post(URL, headers=headers, json=body, timeout=60)
        # 429/529 are TypeSafe's own throttles; 520 came back once from its proxy, 2026-09-23
        if (r.status_code == 429 or r.status_code >= 500) and attempt < 3:
            time.sleep(5 * 2 ** attempt)
            continue
        break
    if r.status_code >= 300:
        raise RuntimeError(f"HTTP {r.status_code} {r.text[:300]}")
    data = r.json()
    scores = {q: data["answers"][q]["noul"] for q in QUESTIONS}
    return scores, data.get("model", "?"), data.get("usage", {}).get("input_tokens", 0)


def check_segment(source_text, rewrite_text):
    """For rewrite_segments.py: one segment's raw text and its rewrite -> (scores, flagged)."""
    state = (f"SOURCE:\n{render(turns_from_source(source_text))}\n\n"
             f"CANDIDATE:\n{render(turns_from_rewrite(rewrite_text))}")
    scores, _, _ = ask(state)
    return scores, [q for q, s in scores.items() if s >= FLAG]


def words(text):
    return re.findall(r"\w+", text.lower())


def published_pairs(tag):
    """Cut raw.md with segment_episode.segment(), then find each segment's start in the
    published interview.md. interview.md has no timestamps, so the cut is found by text:
    the segment's first 15 raw words against every 15-word window near the place the
    segment's share of the raw words predicts. A cut can land inside a joined interview
    turn; that turn is split there and both halves keep its speaker."""
    import common
    import segment_episode
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    ep_dir = ROOT / "episodes" / common.episode_path(common.resolve_tag(manifest, tag))
    fields, _ = common.read_frontmatter_body(ep_dir / "raw.md")
    segs = segment_episode.segment(ep_dir / "raw.md", fields["video_id"], fields["duration_seconds"])
    body = (ep_dir / "interview.md").read_text(encoding="utf-8")
    body = body.split("<!-- /nav -->", 1)[-1]
    iturns = turns_from_rewrite(body)
    # one entry per word token: (turn index, char offset of the token in that turn's text)
    tokens = [(ti, m.start(), m.group().lower()) for ti, (_, what) in enumerate(iturns)
              for m in re.finditer(r"\w+", what)]
    flat = [(ti, c) for ti, c, _ in tokens]
    iw = [w for _, _, w in tokens]
    raw_total = sum(s["words"] for s in segs) or 1

    cuts, done = [0], 0
    for s in segs[1:]:
        done += segs[len(cuts) - 1]["words"]
        anchor = words(turns_from_source(s["text"])[0][1])[:15]
        guess = int(done / raw_total * len(iw))
        last = next(c for c in reversed(cuts) if c is not None)
        lo, hi = max(last + 1, guess - 2500), min(len(iw) - len(anchor), guess + 2500)
        best, at = 0.0, None
        for i in range(lo, hi):
            r = SequenceMatcher(None, anchor, iw[i:i + len(anchor)], autojunk=False).ratio()
            if r > best:
                best, at = r, i
        # the best-scoring window can start a few words early (ep01:bakar seg06 took three
        # words of the previous turn); move it onto the anchor's own first two words
        if at is not None:
            near = [i for i in range(max(lo, at - 6), min(hi, at + 7))
                    if iw[i:i + 2] == anchor[:2]]
            if near:
                at = min(near, key=lambda i: abs(i - at))
        cuts.append(at if best >= 0.5 else None)
        s["_match"] = best
    segs[0]["_match"] = 1.0

    pairs = []
    for k, s in enumerate(segs):
        a = cuts[k]
        b = next((c for c in cuts[k + 1:] if c is not None), len(iw))
        if a is None:
            # no anchor: this segment is folded into the one before by the previous span
            continue
        # slice each interview turn's ORIGINAL text between the two cut tokens
        cand = []
        first_ti, first_c = flat[a]
        last_ti = flat[b - 1][0]
        end_ti, end_c = flat[b] if b < len(flat) else (None, None)
        for ti in range(first_ti, last_ti + 1):
            who, what = iturns[ti]
            start = first_c if ti == first_ti else 0
            stop = end_c if ti == end_ti else len(what)
            if what[start:stop].strip():
                cand.append((who, what[start:stop].strip()))
        src = s["text"]
        j = k + 1
        while j < len(segs) and cuts[j] is None:
            src += "\n\n" + segs[j]["text"]
            j += 1
        pairs.append((k, s["_match"], cleaned(turns_from_source(src)), cand))
    return pairs


def cleaned(turns):
    """The raw side put through the SAME clean_interview.clean_body() the published file got,
    so the edits the owner ruled in -- acknowledgement turns, fillers, echoed slip-ins,
    joined turns -- are not read as a dropped or moved claim. ep01:bakar's `Kenapa 3 bulan?`
    was flagged before this: a sanctioned slip-in drop, not a defect."""
    from clean_interview import clean_body
    body, *_ = clean_body("\n\n".join(f"**{who}:** {what}" for who, what in turns))
    return render(turns_from_rewrite(body))


def rewrite_pairs(tag, lang):
    art = artifact_tag(tag)
    segments = json.loads((ROOT / "data" / f"_{art}_segments.json").read_text(encoding="utf-8"))
    rewrite_dir = ROOT / "data" / f"_{art}_rewrite" / lang
    pairs = []
    for seg in segments:
        idx = int(seg["index"])
        path = rewrite_dir / f"seg{idx:02d}.md"
        if not path.exists():
            print(f"seg{idx:02d}: no rewrite at {path.relative_to(ROOT)}, skipped")
            continue
        pairs.append((idx, 1.0, render(turns_from_source(seg["text"])),
                      turns_from_rewrite(path.read_text(encoding="utf-8"))))
    return pairs


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit("usage: jev_claim_check.py <tag> [--published] [--controls] [--lang=mixed]")
    tag = args[0]
    controls = "--controls" in sys.argv
    lang = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--lang=")), "mixed")
    pairs = published_pairs(tag) if "--published" in sys.argv else rewrite_pairs(tag, lang)

    rows, tokens, model_seen, flagged = [], 0, set(), []
    for idx, match, source, cand in pairs:
        variants = {"real": cand}
        if controls:
            variants.update({"fabricated": fabricated(cand), "swapped": swapped(cand), "cut": cut(cand),
                             "one_swapped": one_swapped(cand), "one_cut": one_cut(cand)})
        for name, turns in variants.items():
            if turns is None:
                continue
            state = f"SOURCE:\n{source}\n\nCANDIDATE:\n{render(turns)}"
            scores, model, used = ask(state)
            tokens += used
            model_seen.add(model)
            rows.append((idx, name, scores))
            hits = [q for q, s in scores.items() if s >= FLAG]
            if name == "real" and hits:
                flagged.append((idx, hits))
            ratio = sum(len(w.split()) for _, w in turns) / max(1, len(source.split()))
            print(f"seg{idx:02d} {name:<10} match {match:.2f}  words {ratio:.2f}  "
                  + "  ".join(f"{q} {s:.2f}" for q, s in scores.items())
                  + ("   FLAG " + ",".join(hits) if name == "real" and hits else ""), flush=True)

    print(f"\nmodel {', '.join(sorted(model_seen))}; {len(rows)} calls; {tokens} input tokens "
          f"(${tokens * 0.042 / 1e6:.4f})")
    print(f"{tag}: {len(flagged)} segment(s) at or above {FLAG}: "
          + ("; ".join(f"seg{i:02d} {','.join(h)}" for i, h in flagged) or "none"))

    if controls:
        print("\nSEPARATION: each question's score on its own control vs on the real rewrite")
        print("  a check is usable only if every control scores above every real rewrite")
        for ctrl, q in CONTROL_TARGET.items():
            real = [s[q] for i, n, s in rows if n == "real"]
            hit = [s[q] for i, n, s in rows if n == ctrl]
            if not hit:
                continue
            ok = min(hit) > max(real)
            print(f"  {q:<14} control '{ctrl}': min {min(hit):.2f}   real: max {max(real):.2f}   "
                  f"{'SEPARATES' if ok else 'OVERLAPS'}")


if __name__ == "__main__":
    main()
