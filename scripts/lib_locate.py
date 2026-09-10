"""Find a turn's text in a second transcript of the same audio, when the words differ.

WHY. An owner decision is recorded against the turn's TEXT as the local ASR heard it
("Kemudian hari Ahad di mana? Di Puchong"). A candidate raw built from MAI's words spells
the same speech differently, splits it over several blocks, and keeps the fillers the local
engine dropped ("[02:10] Kemudian hari Ahad di mana?" / "[02:11] Di Puchong?"). A substring
lookup then finds nothing: 37 of ep61's 44 recorded decisions read as "not locatable"
against the MAI candidate, which is the same blind spot that let one decision be destroyed
before (ATTRIBUTION_PASS.md).

Stamps cannot do the locating on their own. 159 of ep61's 203 block stamps sit more than
10 s away from their own words, and one is 26 s out, so a stamp window lands on the wrong
speaker. So this matches on WORDS -- longest common subsequence of tokens, which tolerates
a different spelling, an inserted filler and a block boundary -- and uses the stamp only to
break a tie between two equally good matches.
"""
import re
from collections import defaultdict
from difflib import SequenceMatcher

BLOCK_RE = re.compile(r"^\[([\d:]+)\]\s*([^:\n]{0,40}?):\s*(.*)$", re.M)
WORD_RE = re.compile(r"[0-9A-Za-z\u00c0-\u024f']+")
MIN_TOKENS = 3
MIN_SCORE = 0.5
ANCHORS = 3


def secs(t):
    q = [int(x) for x in t.split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(q)))


def tokens(text):
    return [w.lower() for w in WORD_RE.findall(text)]


class Doc:
    """A raw-style transcript, indexed by word so a passage can be found in it."""

    def __init__(self, text):
        self.blocks = []          # (stamp string, label, body text)
        self.tok = []             # every word in the file, in order
        self.owner = []           # block index of each word
        self.first = []           # first word index of each block
        for stamp, label, body in BLOCK_RE.findall(text):
            i = len(self.blocks)
            self.blocks.append((stamp, label.strip(), body))
            self.first.append(len(self.tok))
            for w in tokens(body):
                self.tok.append(w)
                self.owner.append(i)
        self.at = defaultdict(list)
        for p, w in enumerate(self.tok):
            self.at[w].append(p)

    def line(self, i):
        stamp, label, body = self.blocks[i]
        return f"[{stamp}] {label}: {body}"

    def window(self, start, n):
        """The window's text plus, per character, the index of the token it came from."""
        toks = self.tok[start:start + n]
        idx = []
        for i, t in enumerate(toks):
            idx.extend([i] * (len(t) + 1))
        return " ".join(toks), idx

    def locate(self, snippet, near=None):
        """Best match for `snippet` in this file. `near` is a second, used only for ties.

        Scored on CHARACTERS, not whole words, because the two engines disagree about Malay
        affixes: the owner's decision reads "pandangan lain sikit" and MAI heard
        "Aku berpandangan lain sikitlah", which shares no whole token but is plainly the
        same three words. Returns None when the snippet is too short to identify a passage
        or when nothing matches half of it, so the caller reports "not locatable" instead
        of guessing.
        """
        q = tokens(snippet)
        if len(q) < MIN_TOKENS:
            return None
        present = [w for w in set(q) if w in self.at]
        if not present:
            return None
        qs = " ".join(q)
        width = len(q) + max(3, len(q) // 2)      # room for MAI's inserted fillers
        anchors = sorted(present, key=lambda w: len(self.at[w]))[:ANCHORS]
        seen, best = set(), []
        for w in anchors:
            for p in self.at[w]:
                for start in range(max(0, p - len(q) + 1), p + 1):
                    if start in seen:
                        continue
                    seen.add(start)
                    ws, idx = self.window(start, width)
                    hit = [b for b in SequenceMatcher(None, qs, ws, autojunk=False)
                           .get_matching_blocks() if b.size >= 2]
                    if not hit:
                        continue
                    matched = sum(b.size for b in hit)
                    c0, c1 = hit[0].b, min(hit[-1].b + hit[-1].size - 1, len(idx) - 1)
                    best.append((matched / len(qs), start + idx[c0], start + idx[c1]))
        if not best:
            return None
        top = max(b[0] for b in best)
        if top < MIN_SCORE:
            return None
        near_top = [b for b in best if b[0] >= top - 0.02]
        if near is not None and len(near_top) > 1:
            near_top.sort(key=lambda b: abs(secs(self.blocks[self.owner[b[1]]][0]) - near))
        score, lo, hi = near_top[0]
        span = sorted({self.owner[p] for p in range(lo, hi + 1)})
        counts = defaultdict(int)
        for p in range(lo, hi + 1):
            counts[self.blocks[self.owner[p]][1]] += 1
        return {"score": score, "tok0": lo, "tok1": hi, "blocks": span,
                "stamp": self.blocks[span[0]][0], "labels": dict(counts),
                "ambiguous": len({b[1] for b in near_top}) > 1}
