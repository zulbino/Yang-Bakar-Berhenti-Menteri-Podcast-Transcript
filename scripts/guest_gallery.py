"""Name a guest's face without a human, when and only when the episode leaves no choice.

WHY. The face gallery names the three regular hosts. 25 episodes have guests, and a guest's
face is "unknown" to the camera reference: their talking seconds leave the UEM, so the
attribution gate cannot see whether a re-cut got the guest right. On ep60 that was 1,659
seconds -- the whole of Sum Dek Jo -- and the split tool refused a change it could not
measure. Naming a face is the one step in this pipeline with no independent check, and the
standing rule is that a speaker is never inferred from text. So this script names a face
only under a bijection it can assert:

  exactly ONE guest in the episode's frontmatter, and
  exactly ONE cluster of unidentified faces that holds nearly all the unidentified talking
  seconds (the rest are b-roll strangers and thumbnails, which do not talk).

Anything else -- two guests, two talking clusters, a rotating host -- stops and prints the
clusters for a person to name with `camera_speakers.py gallery`. The per-episode gallery it
writes is the base gallery plus the guest, with provenance, under data/_face_gallery_<vid>.json
(gitignored: face embeddings are biometric data and are deliberately not committed).

  python scripts/guest_gallery.py ep60
  python scripts/camera_speakers.py reference <vid> --tracks data/_camera_tracks_<vid> \
      --gallery data/_face_gallery_<vid>.json --out data/camera_ref_ep60 --runtime <s>
"""
import glob
import io
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from camera_speakers import FLOOR, MARGIN, SPEAK  # noqa: E402

SIM = 0.60            # a real match to the same face lands at 0.86-0.98 (camera_speakers note 3)
MIN_SHARE = 0.90      # the guest cluster must hold this share of unidentified talking seconds
PER_PERSON = 30
GENERIC = re.compile(r"^(speaker\b|multiple speakers|overlapping|audience|hadirin|unknown|\[)", re.I)


def frontmatter_list(text, key):
    m = re.search(r"^" + key + r":\s*(\[.*\])?\s*\n((?:- .*\n)*)", text, re.M)
    if not m:
        return []
    if m.group(1):
        return [x.strip().strip("'\"") for x in m.group(1).strip("[]").split(",") if x.strip()]
    return [l[2:].strip().strip("'\"") for l in m.group(2).splitlines()]


def main():
    tag = sys.argv[1]
    hits = glob.glob(str(ROOT / f"episodes/*/*-{tag}-*/raw.md"))
    if len(hits) != 1:
        sys.exit(f"{len(hits)} episodes match {tag}")
    folder = Path(hits[0]).parent
    src = folder / "interview.md" if (folder / "interview.md").exists() else folder / "raw.md"
    text = io.open(src, encoding="utf-8").read()
    vid = re.search(r"video_id:\s*(\S+)", text).group(1)
    guests = frontmatter_list(text.split("\n---", 1)[0], "guests")
    hosts = frontmatter_list(text.split("\n---", 1)[0], "hosts")

    base = json.load(io.open(ROOT / "data" / "_face_gallery.json", encoding="utf-8"))
    G = {k: np.array(v) for k, v in base["gallery"].items()}
    unknown_hosts = [h for h in hosts if h.split(" (")[0] not in G]

    # The candidate names are raw.md's own labels: whatever the owner settled on is what the
    # reference has to say, or no word will ever match it. Generic labels are not people.
    raw = io.open(folder / "raw.md", encoding="utf-8").read()
    labels = {m.group(1).strip() for m in re.finditer(r"^\[[\d:]+\]\s*([^:\n]{1,40}?):", raw, re.M)}
    candidates = sorted(l for l in labels
                        if l.split(" (")[0] not in G and not GENERIC.search(l))

    unk = []
    for p in sorted(glob.glob(str(ROOT / f"data/_camera_tracks_{vid}/chunk_*.json"))):
        for tr in json.load(open(p))["tracks"]:
            v = tr.get("vec")
            if not v:
                continue
            v = np.array(v)
            ranked = sorted(((float((M @ v).max()), n) for n, M in G.items()), reverse=True)
            best, second = ranked[0][0], ranked[1][0] if len(ranked) > 1 else 0.0
            if best >= FLOOR and best - second >= MARGIN:
                continue
            talk = sum(1 for x in tr["per_sec"].values() if x > SPEAK)
            unk.append((v / np.linalg.norm(v), talk, len(tr["per_sec"])))
    total_talk = sum(t for _, t, _ in unk)

    clusters = []
    for v, talk, secs in sorted(unk, key=lambda x: -x[2]):
        for c in clusters:
            if max(float(v @ m) for m in c["m"]) >= SIM:
                c["m"].append(v); c["talk"] += talk; c["secs"] += secs
                break
        else:
            clusters.append({"m": [v], "talk": talk, "secs": secs})
    clusters.sort(key=lambda c: -c["talk"])

    print(f"{tag} {vid}: hosts {hosts}, guests {guests}")
    print(f"  {len(unk)} unidentified tracks, {total_talk}s talking, {len(clusters)} clusters:")
    for c in clusters[:6]:
        print(f"    {len(c['m']):>3} tracks  {c['secs']:>5}s on screen  {c['talk']:>5}s talking")

    if unknown_hosts:
        sys.exit(f"  STOP: host(s) {unknown_hosts} are not in the gallery; a person must name them")
    print(f"  raw.md labels not in the gallery: {candidates}")
    if len(candidates) != 1:
        sys.exit(f"  STOP: {len(candidates)} unnamed real label(s) in raw.md, need exactly 1 "
                 f"for the bijection")
    if not clusters or total_talk == 0:
        sys.exit("  STOP: no unidentified talking face; nothing to name")
    top = clusters[0]
    if top["talk"] < MIN_SHARE * total_talk:
        sys.exit(f"  STOP: largest cluster holds {top['talk']}/{total_talk}s of unidentified talking "
                 f"({top['talk'] / total_talk:.0%}); below {MIN_SHARE:.0%}, so a person must decide")

    name = candidates[0].split(" (")[0]
    step = max(1, len(top["m"]) // PER_PERSON)
    vecs = [m.tolist() for m in top["m"][::step]][:PER_PERSON]
    out = {"gallery": dict(base["gallery"], **{name: vecs}),
           "provenance": dict(base.get("provenance", {}),
                              **{name: [{"source": "guest_gallery.py bijection", "episode": vid,
                                         "tracks": len(top["m"]), "talking_s": top["talk"],
                                         "share_of_unidentified_talking": round(top["talk"] / total_talk, 3),
                                         "n_taken": len(vecs)}]})}
    dest = ROOT / "data" / f"_face_gallery_{vid}.json"
    dest.write_text(json.dumps(out), encoding="utf-8")
    print(f"  NAMED {name}: {len(top['m'])} tracks, {top['talk']}s talking "
          f"({top['talk'] / total_talk:.0%} of unidentified) -> {dest}")


if __name__ == "__main__":
    main()
