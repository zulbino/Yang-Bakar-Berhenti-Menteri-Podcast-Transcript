"""Name the guest clusters by word overlap with the previous attribution.

Voiceprints can only name people who have a reference built from trusted episodes, which
means the three recurring hosts. Guests appear once or twice, so verify_speaker_voiceprint
correctly reports them as "not a known speaker" and stops there.

But reattribute_blocks.py leaves the transcript text byte-for-byte identical and only
moves speaker boundaries. So every word exists in both the old and the new attribution,
and each new cluster can be asked: which old label held these same words? For a guest
that answer is unambiguous, because guest labels were the reliable part of the old file --
a guest has a distinctive voice and long uninterrupted answers. It was the co-hosts that
collapsed.

So the division of labour is: voiceprint names the hosts, this names the guests, and any
cluster where the two disagree is left for a human. Never use this for a host label: the
old host attribution is the very thing being replaced, so agreeing with it proves nothing.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TURN = re.compile(r"^\[([0-9:]+)\]\s*([^:]{1,40}?):\s*(.*)$")
HOSTS = {"Rafizi", "Rafizi Ramli", "YB Rafizi", "Haziq", "Farhan (Pa'an)", "Iqbal",
         "Wan Afiq", "Amir Sahmat", "Speaker ?", "Multiple speakers"}


def word_labels(text):
    """[(word, label), ...] in order."""
    out = []
    for line in text.split("# Raw Transcript", 1)[-1].splitlines():
        m = TURN.match(line.strip())
        if m:
            out.extend((w, m.group(2).strip()) for w in m.group(3).split())
    return out


def main():
    ref = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    tags = [a for a in sys.argv[2:] if a.startswith("ep")]
    for path in sorted(ROOT.glob("episodes/*/*/raw.md")):
        tag = re.search(r"ep\d+", path.parent.name).group(0)
        if tags and tag not in tags:
            continue
        rel = path.relative_to(ROOT).as_posix()
        old_text = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=ROOT,
                                  capture_output=True, text=True, encoding="utf-8").stdout
        if not old_text:
            continue
        new = word_labels(path.read_text(encoding="utf-8"))
        old = word_labels(old_text)
        if len(new) != len(old):
            print(f"{tag}: word counts differ ({len(old)} vs {len(new)}), skipped")
            continue
        table = {}
        for (w1, new_lab), (w2, old_lab) in zip(new, old):
            table.setdefault(new_lab, {}).setdefault(old_lab, 0)
            table[new_lab][old_lab] += 1
        print(f"\n=== {tag} ===")
        for new_lab, dist in sorted(table.items(), key=lambda kv: -sum(kv[1].values())):
            total = sum(dist.values())
            top = sorted(dist.items(), key=lambda kv: -kv[1])
            best_lab, best_n = top[0]
            share = 100 * best_n / total
            guest = best_lab not in HOSTS
            verdict = (f"-> {best_lab!r} ({share:.0f}% of its words)" if guest and share >= 70
                       else "-> host or split, use the voiceprint")
            detail = ", ".join(f"{l}={100*n/total:.0f}%" for l, n in top[:3])
            print(f"   {new_lab:<14} {total:>6} words  [{detail}]  {verdict}")


if __name__ == "__main__":
    main()
