"""Split transcript blocks that hold more than one speaker, cutting at the speaker change.

WHY. Measured on ep62 against the camera reference: pyannote finds 573 speaker turns, the
camera finds 671, and raw.md keeps 186 blocks. Block building discards about two thirds of
the boundaries the diarizer already found. 34% of raw.md's blocks hold more than one camera
speaker, and 153 of Haziq's 457 seconds sit under someone else's name because of it. That
is the whole of his 18-point recall gap.

RENAMING BLOCKS DOES NOT FIX IT -- that was tested first, because it moves no text and is
therefore safe. Relabelling each block by the pyannote cluster that dominates it takes
Haziq from 65% to 63%, and on the MAI transcript it takes Farhan from 12% to 0%. The gain
only exists if the text is actually cut, so there is no risk-free version of this change.

WHERE THE WORD TIMES COME FROM. raw.md carries no word times. MAI transcribed the same
audio and returns them, so every raw.md word is aligned to MAI's word sequence and borrows
its clock; unmatched words are interpolated between the nearest matches. On ep62 that
matches 89.6% of words exactly, the largest interpolated gap is 33 words, and no word's
time runs backwards. The residual error against the existing block stamps is 1.9s median,
which at this speech rate is about five words -- so the cut point is approximate and the
guards below exist to keep an approximate cut from doing damage.

FOUR GUARDS, and the script refuses to write if any fails.

  1. WORD COUNT IS IDENTICAL. Splitting moves words between blocks. It must never add,
     drop, duplicate or reorder one. Checked as an ordered list, not a multiset.
  2. NO SHREDDING. A run must reach both MIN_RUN_WORDS and MIN_RUN_S to become its own
     block. The previous re-cutting pass tore turns into 1-3 word scraps under alternating
     names -- 306 isolated tears and 267 alternating chains, which cannot be repaired from
     text afterwards because the scrap is often genuine and the neighbour's tail is what
     is misnamed.
  3. STAMPS STAY STRICTLY INCREASING. A split that emits a block starting before the one
     before it has cut in the wrong place.
  4. THE RESULT IS SCORED BEFORE IT IS KEPT. --reference scores word-level attribution
     against a camera RTTM and refuses to write if it gets worse.

  python scripts/split_mixed_blocks.py ep62 --reference data/camera_ref_ep62.rttm
  python scripts/split_mixed_blocks.py ep62 --reference data/camera_ref_ep62.rttm --write
"""
import argparse
import glob
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

MIN_RUN_WORDS = 4      # below this a run is a scrap, not a turn
MIN_RUN_S = 1.5        # ep51's confirmed short turns run past a second
BLOCK_RE = re.compile(r"^\[([\d:]+)\]\s*([^:\n]{0,40}?):\s*(.*)$", re.M)


def secs(t):
    q = [int(x) for x in t.split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(q)))


def fmt(s):
    s = int(s)
    return f"{s//3600}:{s%3600//60:02d}:{s%60:02d}" if s >= 3600 else f"{s//60:02d}:{s%60:02d}"


def short(label):
    """`Farhan (Pa'an)` and `Farhan` are one person.

    raw.md carries a parenthesised alias on some labels. Building cluster names from the
    stripped form while guarding on the full form made every Farhan word compare unequal
    to itself, and reported his recall collapsing from 78% to 14% when nothing had moved.
    One canonical form, used everywhere.
    """
    return label.split(" (")[0].strip()


def normword(w):
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", w.lower()))


def mai_word_times(video_id):
    out = []
    for p in sorted(glob.glob(str(ROOT / f"data/_mai_{video_id}/mai_response_*.json"))):
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        base = d["_chunk_start_s"]
        for ph in d["phrases"]:
            for w in ph.get("words", []):
                out.append((w["text"], base + w["offsetMilliseconds"] / 1000))
    return out


def borrow_times(raw_words, mai):
    """Align the local ASR's words to MAI's and borrow the clock."""
    from rapidfuzz.distance import Levenshtein
    vocab = {}
    ai = [vocab.setdefault(normword(w), len(vocab)) for w in raw_words]
    bi = [vocab.setdefault(normword(w), len(vocab)) for w, _ in mai]
    matched, si, di = {}, 0, 0
    for op in Levenshtein.editops(ai, bi):
        while si < op.src_pos and di < op.dest_pos:
            matched[si] = di
            si += 1
            di += 1
        if op.tag == "replace":
            si += 1
            di += 1
        elif op.tag == "delete":
            si += 1
        else:
            di += 1
    while si < len(ai) and di < len(bi):
        matched[si] = di
        si += 1
        di += 1
    times = [None] * len(raw_words)
    for a, b in matched.items():
        times[a] = mai[b][1]
    known = [i for i, t in enumerate(times) if t is not None]
    if not known:
        sys.exit("no word matched MAI -- cannot borrow a clock")
    for i in range(len(times)):
        if times[i] is not None:
            continue
        lo = next((k for k in reversed(known) if k < i), None)
        hi = next((k for k in known if k > i), None)
        if lo is not None and hi is not None:
            times[i] = times[lo] + (times[hi] - times[lo]) * (i - lo) / (hi - lo)
        else:
            times[i] = times[lo if lo is not None else hi]
    return times, len(matched)


def per_second(triples):
    out = {}
    for a, b, who in triples:
        for t in range(int(a), int(b)):
            out[t] = str(who)
    return out


def smooth(runs, keep_name=None):
    """Fold runs too short to be a turn into the neighbour they most resemble.

    A RUN CARRYING THE BLOCK'S ORIGINAL LABEL IS NEVER FOLDED, however short. That label
    already survived the pipeline and the owner's corrections, so the length test is only
    there to stop a NEW name being introduced on the strength of a one-word flicker.
    Applying it to the original label instead destroys the minority speaker: Farhan speaks
    233 words across 103 seconds in short bursts, almost all of them under four words, and
    folding those took him from 78% to 14%.
    """
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, r in enumerate(runs):
            words, span = len(r["w"]), r["t1"] - r["t0"]
            if r["n"] == keep_name or (words >= MIN_RUN_WORDS and span >= MIN_RUN_S):
                continue
            j = i - 1 if i > 0 else i + 1
            if i > 0 and i < len(runs) - 1:
                j = i - 1 if len(runs[i - 1]["w"]) >= len(runs[i + 1]["w"]) else i + 1
            runs[j]["w"] = (runs[j]["w"] + r["w"]) if j < i else (r["w"] + runs[j]["w"])
            runs[j]["t0"] = min(runs[j]["t0"], r["t0"])
            runs[j]["t1"] = max(runs[j]["t1"], r["t1"])
            del runs[i]
            changed = True
            break
    return runs


SENTENCE_END = re.compile(r"[.?!]$")
SNAP_WINDOW = 3


def snap_to_sentences(runs, window=SNAP_WINDOW):
    """Move a cut to the nearest sentence end within a few words.

    The word clock is borrowed from a second engine and carries about 2s of error, which
    is roughly five words here, so a cut placed purely on time lands mid-sentence about as
    often as not. Punctuation marks a real syntactic break that the clock does not know
    about. The owner caught this on ep62: Farhan asks "Dia buat satu company to hold all
    the assets?" and the cut fell before "assets", handing one word of his question to
    Rafizi and leaving Farhan's sentence unfinished.

    A cut is only moved, never added or removed, and only within `window` words, so a
    genuine mid-sentence interruption more than three words from a full stop survives.
    """
    for i in range(len(runs) - 1):
        left, right = runs[i], runs[i + 1]
        if SENTENCE_END.search(left["w"][-1]):
            continue                                  # already on a sentence end
        best = None
        for n in range(1, window + 1):
            if len(right["w"]) > n and SENTENCE_END.search(right["w"][n - 1]):
                best = ("right", n)
                break
            if len(left["w"]) > n and SENTENCE_END.search(left["w"][-n - 1]):
                best = ("left", n)
                break
        if not best:
            continue
        side, n = best
        if side == "right":
            left["w"] += right["w"][:n]
            del right["w"][:n]
        else:
            right["w"][:0] = left["w"][-n:]
            del left["w"][-n:]
    return [r for r in runs if r["w"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode")
    ap.add_argument("--reference", help="camera RTTM, to score the result")
    ap.add_argument("--diarization", help="pyannote triples json")
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    hits = glob.glob(str(ROOT / f"episodes/*/*-{a.episode}-*/raw.md"))
    if len(hits) != 1:
        sys.exit(f"{len(hits)} raw.md match {a.episode}; both shows have ep01-ep06, "
                 f"so name the episode by its slug: {hits}")
    path = Path(hits[0])
    text = path.read_text(encoding="utf-8")
    head, body = text.split("# Raw Transcript", 1)
    blocks = BLOCK_RE.findall(body)
    vid = re.search(r"video_id:\s*(\S+)", head).group(1)

    # THE SPLIT SOURCE CAN BE THE CAMERA INSTEAD OF pyannote, and on an episode that has a
    # camera reference it should be. pyannote is wrong in precisely the places that matter:
    # at 1:00:08 and 1:05:18 on ep62 it agreed with a wrong label while the camera showed a
    # continuous Rafizi run, so the splitter left both alone and the owner found them by
    # reading. The cost is that a camera-sourced split can no longer be VALIDATED against
    # the camera -- that check becomes circular, and --reference will say so.
    diar = a.diarization or str(ROOT / f"data/diar_{vid}_t055.json")
    if not Path(diar).exists():
        sys.exit(f"{diar} not found")
    if diar.endswith(".rttm"):
        trip = []
        for line in open(diar):
            q = line.split()
            trip.append((float(q[3]), float(q[3]) + float(q[4]), q[7]))
    else:
        trip = json.loads(Path(diar).read_text(encoding="utf-8"))
    pya = per_second(trip)
    circular = a.reference and Path(diar).resolve() == Path(a.reference).resolve()

    words, owner = [], []
    for i, (_, _, t) in enumerate(blocks):
        for w in t.split():
            words.append(w)
            owner.append(i)
    times, nmatch = borrow_times(words, mai_word_times(vid))
    print(f"{len(words)} words, {nmatch} matched to MAI ({nmatch/len(words):.1%})")

    # Name each pyannote cluster by the block label it most overlaps. No camera is used,
    # so the names are exactly what the pipeline already produces and only cuts change.
    vote = defaultdict(Counter)
    for w_i, t in enumerate(times):
        c = pya.get(int(t))
        if c:
            vote[c][short(blocks[owner[w_i]][1])] += 1
    cname = {c: v.most_common(1)[0][0] for c, v in vote.items()}
    # A NEW SPEAKER INTRODUCED BY A SPLIT MUST GET THE FILE'S OWN LABEL TEXT. Cluster names
    # are the short form, so a split that discovers Farhan inside a Rafizi block wrote a
    # bare `Farhan:` next to 27 existing `Farhan (Pa'an):` labels. Map back to whichever
    # full form the file already uses most.
    forms = Counter(b[1].strip() for b in blocks)
    canon = {}
    for full, n in forms.most_common():
        canon.setdefault(short(full), full)
    for c, n in sorted(cname.items()):
        print(f"  {c} -> {n} ({vote[c][n]}/{sum(vote[c].values())})")

    # A SPEAKER WHO OWNS NO CLUSTER CANNOT SURVIVE A SPLIT. Cluster names come from a
    # word-count vote, so a minority speaker who shares every cluster with a louder one is
    # never a cluster's name. Inside such a speaker's block every word maps to somebody
    # else's run, `keep_name` never matches, and a split silently deletes the label from
    # the file -- ep61's owner-confirmed Farhan turn has exactly this shape. Those blocks
    # are left whole. This script may cut blocks; it may not erase a speaker.
    named = set(cname.values())
    protected = Counter()

    out, nsplit = [], 0          # entries are (stamp_seconds, label, text, block_index)
    wi = 0
    for i, (stamp, who, txt) in enumerate(blocks):
        bw = txt.split()
        label = short(who)
        if not bw:
            out.append((secs(stamp), who.strip(), txt, i))
            continue
        if label not in named:
            protected[who.strip()] += 1
            out.append((secs(stamp), who.strip(), txt, i))
            wi += len(bw)
            continue
        runs, cur = [], None
        for k, w in enumerate(bw):
            c = pya.get(int(times[wi + k]))
            nm = cname.get(c, label) if c else (cur["n"] if cur else label)
            if cur and cur["n"] == nm:
                cur["w"].append(w)
                cur["t1"] = times[wi + k]
            else:
                if cur:
                    runs.append(cur)
                cur = {"n": nm, "w": [w], "t0": times[wi + k], "t1": times[wi + k]}
        runs.append(cur)
        runs = smooth(runs, keep_name=label)
        # MERGE ADJACENT RUNS THAT SHARE A NAME BEFORE EMITTING. Smoothing can leave two
        # neighbouring runs with the same speaker, and emitting them separately splits a
        # phrase for no reason: "Sesama. Tak tahu" came out as "Sesama. Tak" + "tahu",
        # both labelled Rafizi. A split is only ever worth making between two DIFFERENT
        # speakers.
        merged = []
        for r in runs:
            if merged and merged[-1]["n"] == r["n"]:
                merged[-1]["w"] += r["w"]
                merged[-1]["t1"] = r["t1"]
            else:
                merged.append(r)
        runs = merged
        runs = snap_to_sentences(runs)
        if len(runs) > 1:
            nsplit += 1
            for k, r in enumerate(runs):
                # keep the file's own label text, alias and all, for the run that kept the
                # block's speaker -- `Farhan (Pa'an)` must not silently become `Farhan`
                nm = who.strip() if r["n"] == label else canon.get(r["n"], r["n"])
                # The first piece keeps the block's own stamp, like an unsplit block does.
                # Only the later pieces take the clock from the word times, so a file whose
                # stamps drift does not get its existing stamps rewritten by a split.
                out.append((secs(stamp) if k == 0 else r["t0"], nm, " ".join(r["w"]), i))
        else:
            # A BLOCK THAT DOES NOT SPLIT KEEPS ITS ORIGINAL LABEL AND STAMP. Overwriting
            # it with pyannote's name is the rename-only change that was already measured
            # and rejected: it takes Haziq from 65% to 63%, and it cost Farhan 12 words at
            # block edges here. This script may cut blocks; it may not re-name them.
            out.append((secs(stamp), who.strip(), txt, i))
        wi += len(bw)
    if protected:
        print("  left whole, speaker owns no cluster: "
              + ", ".join(f"{n} x{c}" for n, c in protected.most_common()))

    # guard 1: the word sequence must be identical, in order
    before = [w for b in blocks for w in b[2].split()]
    after = [w for _, _, t, _ in out for w in t.split()]
    if before != after:
        sys.exit(f"REFUSING: word sequence changed, {len(before)} -> {len(after)}")
    # guard 3: stamps strictly increasing. A backward stamp here is the FILE's stamp being
    # off against the word clock (ep61: 159 of 203 stamps more than 10s out), not a wrong
    # cut, because the first piece of every split keeps its block's own stamp. A small
    # collision is nudged and reported; a large one means the episode needs retiming
    # before it is re-cut, and that is refused rather than papered over.
    MAX_NUDGE_S = 30
    nudged, worst = 0, 0
    for i in range(1, len(out)):
        if out[i][0] <= out[i - 1][0]:
            worst = max(worst, out[i - 1][0] - out[i][0])
            nudged += 1
            out[i] = (out[i - 1][0] + 1,) + out[i][1:]
    if nudged:
        print(f"  {nudged} non-increasing stamps nudged by 1s, worst collision {worst:.0f}s")
    if worst > MAX_NUDGE_S:
        sys.exit(f"REFUSING: a split lands {worst:.0f}s before the previous block's stamp; "
                 f"retime the episode first (retime_blocks.py)")
    print(f"{len(blocks)} blocks -> {len(out)} ({nsplit} split), word sequence identical")

    if a.reference:
        ref = {}
        for line in open(a.reference):
            p = line.split()
            s0, d = float(p[3]), float(p[4])
            for s in range(int(s0), int(s0 + d)):
                ref[s] = p[7]
        def word_score(assign):
            hit = Counter(); tot = Counter()
            for k, t in enumerate(times):
                r = ref.get(int(t))
                if not r:
                    continue
                tot[r] += 1
                if assign[k] == r:
                    hit[r] += 1
            return hit, tot
        old_assign = [short(blocks[owner[k]][1]) for k in range(len(words))]
        new_assign = []
        for _, nm, txt, _ in out:
            for _ in txt.split():
                new_assign.append(short(nm))
        print(f"\nWORD-level attribution against {Path(a.reference).name}:"
              + ("   [CIRCULAR -- this is also the split source, so it is a consistency"
                 " check, NOT a validation]" if circular else ""))
        gain = {}
        for tag, assign in (("before", old_assign), ("after ", new_assign)):
            hit, tot = word_score(assign)
            parts = [f"{n} {hit[n]/max(tot[n],1):>4.0%} ({hit[n]}/{tot[n]})"
                     for n in sorted(tot, key=lambda x: -tot[x])]
            allhit, alltot = sum(hit.values()), sum(tot.values())
            print(f"  {tag}  overall {allhit/max(alltot,1):>5.1%}   " + "   ".join(parts))
            gain[tag.strip()] = (allhit, alltot, dict(hit), dict(tot))
        b_hit, b_tot, bh, bt = gain["before"]
        a_hit, a_tot, ah, at = gain["after"]
        worse = [n for n in bt if ah.get(n, 0)/max(at.get(n, 1), 1) < bh[n]/max(bt[n], 1) - 0.02]
        if a_hit < b_hit or worse:
            print(f"  REFUSING to write: overall {b_hit}->{a_hit}, worse for {worse}")
            sys.exit(2)

    if not a.write:
        print("\ndry run. add --write to apply")
        return
    path.write_text(head + "# Raw Transcript" + rebuild(body, len(blocks), out),
                    encoding="utf-8", newline="")
    print(f"\nwritten: {path}")


def rebuild(body, nblocks, out):
    """Rebuild the body line by line, replacing only the block lines.

    Rebuilding from `out` alone deleted every line that is not a `[stamp] Label:` block --
    37 stage directions such as `[00:00] [Music / Intro]` across 21 episodes -- and guard 1
    could not see it, because both sides of its comparison were built from the matched
    blocks only. `out` entries are (stamp_seconds, label, text, block_index).
    """
    by_block = defaultdict(list)
    for t, nm, txt, i in out:
        by_block[i].append(f"[{fmt(t)}] {nm}: {txt}")
    new_lines, j = [], 0
    for line in body.split("\n"):
        if BLOCK_RE.fullmatch(line):
            new_lines.append("\n\n".join(by_block[j]))
            j += 1
        else:
            new_lines.append(line)
    if j != nblocks:
        sys.exit(f"REFUSING: matched {j} block lines while parsing found {nblocks}")
    new_body = "\n".join(new_lines)
    kept = [l for l in body.split("\n") if l.strip() and not BLOCK_RE.fullmatch(l)]
    if any(l not in new_body for l in kept):
        sys.exit("REFUSING: a non-block line would be lost")
    return new_body


if __name__ == "__main__":
    main()
