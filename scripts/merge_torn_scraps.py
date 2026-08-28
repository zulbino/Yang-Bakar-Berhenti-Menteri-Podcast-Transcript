"""Report 1-3 word scraps that forced alignment tore out of a neighbour's sentence.

`lib_local_asr._speaker_lines` labels every word by which diarization turn it overlaps,
which is right in principle and is what stopped short interjections being swallowed. But
near a real speaker change the word-level decision flickers, so a word or two lands under
the wrong name mid-sentence and becomes its own "turn":

    Haziq:  ...bom jangka yang meletup ni Saya
    Rafizi: bukan
    Haziq:  pakar
    Rafizi: Indonesia lah. Jadi saya

That is one sentence, "Saya bukan pakar Indonesia lah", shredded across two speakers.
An earlier fix (2026-08-25) handled the case where a word had NO diarization overlap and
became a "Speaker ?" orphan. This handles the harder case: the word got a real overlap,
just the wrong one.

The signature has to be tight, because genuine short interjections look superficially
similar and this corpus is full of real ones. All four conditions must hold:

  1. The scrap is at most SCRAP_MAX_WORDS words.
  2. It starts lowercase, so it resumes a sentence rather than beginning one. A real
     interjection reads "Tak kelakar." or "Okey." -- capitalised and self-contained.
  3. The turn before it does not end in . ? or !, so that sentence was cut off.
  4. The turns either side carry the SAME label, differing from the scrap's, and BOTH
     are substantial turns rather than scraps themselves.

Condition 4's second half is what keeps this honest. Where labels alternate word by word
the tear is a CHAIN, and text cannot say which speaker owns the sentence. ep12 [1:11:26]
reads Haziq "...meletup ni Saya" / Rafizi "bukan" / Haziq "pakar" / Rafizi "Indonesia
lah": the sentence is "Saya bukan pakar Indonesia lah" and it is Rafizi's, so the tail of
Haziq's turn belongs to Rafizi too. Folding the scrap into the surrounding label would
move the boundary the wrong way and assert something false. Chains are therefore left
alone and reported separately, for the acoustic pass in reattribute_blocks.py to settle.

Condition 2 is doing most of the work. An earlier draft of this check also treated a
list of Malay particles as mid-sentence markers and matched 2,181 spans, most of them
legitimate ("Tak kelakar.", "Ya, saya ke sini pada malam ni.", "Okey.") -- because Tak,
Ya and Okey are ordinary sentence openers here. Requiring a lowercase start cut that to
548, and every sampled one is a real tear.

DELIBERATELY REPORT-ONLY. Merging these looks obvious and is wrong. An earlier version
of this file folded each scrap into the surrounding label and was verified before being
applied, which is the only reason it never shipped:

    ep12 [07:58]  Rafizi "...beria beria beria ok" | Haziq "beria ok seterusnya"
    ep13 [03:06]  Haziq "...Ahli politik dia tak boleh. TikTok" | Rafizi "pun tak boleh?"
    ep21          Rais "...Become the PM. Oh, ya, ya. I" | Rafizi "insisted."

"beria ok seterusnya" is the run-sheet voice, which is never Rafizi. "TikTok pun tak
boleh?" is a real question. "I insisted" is Rafizi's line, which Rais then echoes as "Yes,
you insisted". In all three the scrap is a genuine short turn and the NEIGHBOUR'S TAIL is
what sits under the wrong name, so folding the scrap inward asserts the exact opposite of
the truth. Direction is not recoverable from text; only the audio knows.

So this counts the damage and nothing else. The cause is fixed acoustically in
reattribute_blocks.py by smoothing sub-second islands out of the diarization before words
are labelled, and this script measures what is left afterwards.
"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRAP_MAX_WORDS = 3
TURN = re.compile(r"^\[([0-9:]+)\]\s*([^:]{1,40}?):\s*(.*)$")


def parse(body):
    turns = []
    for line in body.splitlines():
        m = TURN.match(line.strip())
        if m:
            turns.append([m.group(1), m.group(2).strip(), m.group(3).strip()])
    return turns


def _scrappy(turn):
    return len(turn[2].split()) <= SCRAP_MAX_WORDS


def is_tear(prev, scrap, nxt):
    """An ISOLATED tear: one scrap between two substantial turns of the same speaker."""
    if prev[1] != nxt[1] or prev[1] == scrap[1]:
        return False
    text = scrap[2]
    if not text or len(text.split()) > SCRAP_MAX_WORDS:
        return False
    if not text[0].islower():
        return False
    if _scrappy(prev) or _scrappy(nxt):
        return False                      # part of an alternating chain -- not decidable here
    return not (prev[2] and prev[2][-1] in ".?!")


def is_chain(turns, i):
    """Scrap at i whose neighbourhood alternates, so ownership needs audio."""
    if not (1 <= i <= len(turns) - 2):
        return False
    scrap = turns[i]
    if not scrap[2] or len(scrap[2].split()) > SCRAP_MAX_WORDS or not scrap[2][0].islower():
        return False
    return _scrappy(turns[i - 1]) or _scrappy(turns[i + 1])


def merge_once(turns):
    """One pass. Returns (new_turns, [(timestamp, label, scrap, host_label), ...])."""
    out, merged, i = [], [], 0
    while i < len(turns):
        if 1 <= i <= len(turns) - 2 and out and is_tear(turns[i - 1], turns[i], turns[i + 1]):
            host = out[-1]
            merged.append((turns[i][0], turns[i][1], turns[i][2], host[1]))
            host[2] = f"{host[2]} {turns[i][2]} {turns[i + 1][2]}".strip()
            i += 2
            continue
        out.append(list(turns[i]))
        i += 1
    return out, merged


def fix_body(body):
    turns = parse(body)
    all_merged = []
    for _ in range(6):
        turns, merged = merge_once(turns)
        if not merged:
            break
        all_merged.extend(merged)
    chains = [turns[i] for i in range(len(turns)) if is_chain(turns, i)]
    return turns, all_merged, chains


def main():
    write = False  # never: see the module docstring
    only = [a for a in sys.argv[1:] if a.startswith("ep")]
    total, files = 0, 0
    chain_total, chain_eps = [0], set()
    for path in sorted(ROOT.glob("episodes/*/*/raw.md")):
        tag = re.search(r"ep\d+", path.parent.name).group(0)
        if only and tag not in only:
            continue
        text = path.read_text(encoding="utf-8")
        head, body = text.split("# Raw Transcript", 1)
        turns, merged, chains = fix_body(body)
        chain_total[0] += len(chains)
        if chains:
            chain_eps.add(tag)
        if not merged:
            continue
        files += 1
        total += len(merged)
        label = f"{tag}{'(24)' if 'bakar' in str(path) else ''}"
        print(f"\n{label}: {len(merged)} tear(s) reassembled")
        for ts, lab, scrap, host in merged:
            print(f"   [{ts:>8}] {scrap!r} was {lab!r} -> folded into {host!r}")
        if write:
            new_body = "\n\n" + "\n\n".join(f"[{t[0]}] {t[1]}: {t[2]}" for t in turns) + "\n"
            path.write_text(head + "# Raw Transcript" + new_body, encoding="utf-8")
    print("")
    print(f"{total} isolated tears across {files} files")
    print(f"{chain_total[0]} alternating chains across {len(chain_eps)} episodes "
          "left alone -- text cannot say who owns the sentence, the acoustic pass must")
    print("report only -- these are NOT auto-fixable, see the module docstring")


if __name__ == "__main__":
    main()
