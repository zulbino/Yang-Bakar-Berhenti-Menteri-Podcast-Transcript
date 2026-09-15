"""Name a face the corpus cannot name, using evidence outside the episode.

WHY THIS EXISTS. The owner asked for it on 2026-09-13: "can we make another rule, do
make a verification loop via tools at hand, web search, social media etc then build it
up to confidently identify instead of waiting for me. I dont want to be a blocker."
ep39 is the case that prompted it: a real speaker talks for 435 s, the show calls him
`Iqbal`, and `guest_gallery.py` correctly refused to name his face because its
one-guest bijection did not apply. The old answer was to wait for a person. This is
the measured alternative.

WHAT IT IS. A public photograph of a named person is an INDEPENDENT WITNESS, in the
same sense as the camera in `camera_speakers.py`: no audio model made it, and it was
not derived from this corpus. So it can be compared against a face cluster the same
way `camera_speakers.py` compares a track against the gallery -- SFace embeddings,
cosine distance, a floor and a margin.

WHY IT NEEDS CALIBRATION BEFORE IT MAY WRITE ANYTHING. A web photo is a different
camera, a different year, a different light. CLAUDE.md rule 8 says a probabilistic
vote is not identification; only a witness measured on a held-out class may write a
label. So `calibrate` runs the matcher against people whose faces the gallery ALREADY
holds (Rafizi, Haziq, Farhan) and prints the full cosine matrix. Read that matrix
before trusting any `match` result: the diagonal has to win, and it has to win by more
than the off-diagonal spread. If it does not, the photo is unusable and the answer is
still to escalate.

TWO FAILURE MODES THIS GUARDS AGAINST.

  - The wrong person in the photo. A web search for a common Malay given name returns
    several different people. `match` therefore requires the name to be SOURCED from
    the episode's own text or the show's description, and prints the photo URL next to
    the verdict so the provenance travels with the label.
  - A cluster that is really two people. A high cosine against a mixed cluster names
    both of them at once. `match` prints the cluster's own internal spread, so a loose
    cluster is visible rather than silently accepted.

  python scripts/identify_person.py calibrate --photos "Rafizi=https://...jpg" "Haziq=https://...jpg"
  python scripts/identify_person.py match --census data/_face_census_XH1dBHPPRbs.json \
      --clusters data/_clusters_XH1dBHPPRbs.json --name "Iqbal Fatkhi" --photo https://...png
"""
import argparse
import hashlib
import json
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import camera_speakers as cs  # noqa: E402

CACHE = cs.ROOT / "data" / "_refphotos"
UA = "Mozilla/5.0 (compatible; YBM-transcript-research/1.0)"


def fetch(url):
    """Download a reference photo once. Named by URL so a re-run costs nothing."""
    CACHE.mkdir(parents=True, exist_ok=True)
    # hashlib, NOT hash(): Python randomises string hashing per process (PYTHONHASHSEED),
    # so the first version re-downloaded every photo on every run and left a duplicate
    # behind each time. Found in the 2026-09-14 cleanup, with two copies of the same image
    # under different names.
    name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    dest = CACHE / (name + Path(url.split("?")[0]).suffix)
    if not dest.exists():
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        for wait in (0, 5, 20):        # Wikimedia answers 429 to a burst of image fetches
            time.sleep(wait)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    dest.write_bytes(r.read())
                break
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    raise
        else:
            sys.exit(f"429 after three tries: {url}")
    return dest


def photo_vec(det, rec, path):
    """The SFace vector of the largest face in a still image, or None."""
    img = cv2.imread(str(path))
    if img is None:
        return None
    h, w = img.shape[:2]
    det.setInputSize((w, h))
    _, faces = det.detect(img)
    if faces is None or not len(faces):
        return None
    f = max(faces, key=lambda f: f[2] * f[3])
    return cs._unit(rec.feature(rec.alignCrop(img, f)).flatten())


def gallery_centroids(path):
    g = json.loads(Path(path).read_text())["gallery"]
    return {n: cs._unit(np.mean(np.array(v), axis=0)) for n, v in g.items()}


def cmd_calibrate(a):
    det, rec = cs._models()
    cents = gallery_centroids(a.gallery)
    names = sorted(cents)
    print(f"gallery holds {len(names)}: {', '.join(names)}")
    print("cosine of each reference PHOTO against each gallery face.")
    print("the diagonal must win, and by more than the off-diagonal spread.\n")
    print("photo of".ljust(18) + "".join(n[:12].ljust(14) for n in names) + "verdict")
    for spec in a.photos:
        who, url = spec.split("=", 1)
        v = photo_vec(det, rec, fetch(url))
        if v is None:
            print(f"{who.ljust(18)}NO FACE DETECTED in {url}")
            continue
        sims = {n: float(v @ cents[n]) for n in names}
        best = max(sims, key=sims.get)
        second = sorted(sims.values())[-2] if len(sims) > 1 else 0.0
        ok = best == who and sims[best] >= cs.FLOOR and sims[best] - second >= cs.MARGIN
        row = "".join(f"{sims[n]:+.3f}".ljust(14) for n in names)
        print(f"{who.ljust(18)}{row}{'RIGHT' if ok else 'WRONG or below bar'}"
              f"  best={best} margin={sims[best] - second:+.3f}")


# Two clusters are the SAME PERSON when their centroids are close AND they never appear in
# the same sampled second. Cross-cluster cosine for one face measures 0.82-0.92 here and
# cross-person tops out near 0.37, so 0.60 separates them with room to spare; the shared-
# second test is the hard veto, because two faces in one frame are two people whatever the
# cosine says. camera_speakers.py's cluster stage already warns that glasses, profile and
# lighting each split one person into several clusters -- this is that warning applied to
# the match, which otherwise measures a man's margin against himself.
SAME_FACE = 0.60


def people(M, lab, T, min_size):
    """Group clusters into people. Returns [[cluster ids], ...]."""
    ids = [c for c in sorted(set(lab.tolist())) if (lab == c).sum() >= min_size]
    cent = {c: cs._unit(M[lab == c].mean(axis=0)) for c in ids}
    secs = {c: set(T[lab == c].tolist()) for c in ids}
    groups = []
    for c in ids:
        for g in groups:
            if all(float(cent[c] @ cent[o]) >= SAME_FACE and not (secs[c] & secs[o])
                   for o in g):
                g.append(c)
                break
        else:
            groups.append([c])
    return groups


def cmd_match(a):
    det, rec = cs._models()
    rows = json.loads(Path(a.census).read_text())
    lab = np.array(json.loads(Path(a.clusters).read_text())["labels"])
    M = np.array([r["vec"] for r in rows])

    v = photo_vec(det, rec, fetch(a.photo))
    if v is None:
        sys.exit(f"no face detected in {a.photo} -- find another photograph")

    known = gallery_centroids(a.gallery) if a.gallery else {}
    T = np.array([r["t"] for r in rows])
    out = []
    for g in people(M, lab, T, a.min_size):
        # SCORE A PERSON ON THEIR BEST CLUSTER, NOT ON THE MEAN OF THEIR CLUSTERS. This is
        # the rule camera_speakers.py already states for its gallery: "a multi-vector
        # gallery per person, matched on the MAXIMUM similarity". Averaging a profile
        # cluster into a frontal one moves the centroid away from BOTH views, so ep52's
        # Zaim fell from +0.676 to +0.540 and dropped under the floor while his margin over
        # the next person GREW to +0.350. A person is not the average of the angles they
        # were filmed from.
        cents = {c: cs._unit(M[lab == c].mean(axis=0)) for c in g}
        best_c = max(g, key=lambda c: float(v @ cents[c]))
        idx = np.where(np.isin(lab, g))[0]
        bidx = np.where(lab == best_c)[0]
        secs = sorted(rows[i]["t"] for i in idx)
        out.append({"cluster": "+".join(str(c) for c in g), "n": len(idx),
                    "cohesion": float(np.mean(M[bidx] @ cents[best_c])),
                    "sim": float(v @ cents[best_c]),
                    "known": max(known, key=lambda n: v @ known[n]) if known else None,
                    "known_sim": max((max(float(cents[c] @ known[n]) for c in g)
                                      for n in known), default=0.0),
                    "first": cs.hms(secs[0]), "last": cs.hms(secs[-1])})

    out.sort(key=lambda r: -r["sim"])
    print(f"photo: {a.photo}")
    print(f"name claimed: {a.name}\n")
    print("person (clusters)  faces  cohesion  cos(photo)  cos(best known)  span")
    for r in out[:a.top]:
        print(f"{r['cluster']:>17}  {r['n']:>5}  {r['cohesion']:>8.3f}  "
              f"{r['sim']:>+10.3f}  {r['known_sim']:>+15.3f}  {r['first']}-{r['last']}")

    best, second = out[0], (out[1] if len(out) > 1 else None)
    margin = best["sim"] - (second["sim"] if second else 0.0)
    print(f"\nbest cluster {best['cluster']}: cos {best['sim']:+.3f}, "
          f"margin over next {margin:+.3f}, floor {cs.FLOOR}, required margin {cs.MARGIN}")
    if best["sim"] < cs.FLOOR:
        print(f"REFUSE: below the floor. {a.name} is not measurably any of these faces.")
    elif margin < cs.MARGIN:
        print(f"REFUSE: two PEOPLE are too close to separate. Escalate with a link.")
    elif best["known_sim"] >= cs.FLOOR:
        print(f"REFUSE: cluster(s) {best['cluster']} already match a gallery face "
              f"at {best['known_sim']:+.3f}. Naming it would rename a known person.")
    else:
        # One --name per cluster: cmd_gallery parses a single cluster id, and a person
        # who owns two clusters must contribute both or the gallery keeps one angle only.
        args = " ".join(f'--name "{c}={a.name}"' for c in best["cluster"].split("+"))
        print(f"ACCEPT: enrol cluster(s) {best['cluster']} as {a.name}. Then run")
        print(f"  python scripts/camera_speakers.py gallery {args}")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("calibrate")
    c.add_argument("--photos", nargs="+", required=True, metavar="NAME=URL")
    c.add_argument("--gallery", default=str(cs.ROOT / "data" / "_face_gallery.json"))
    c.set_defaults(fn=cmd_calibrate)

    m = sub.add_parser("match")
    m.add_argument("--census", required=True)
    m.add_argument("--clusters", required=True)
    m.add_argument("--name", required=True)
    m.add_argument("--photo", required=True)
    m.add_argument("--gallery", default=str(cs.ROOT / "data" / "_face_gallery.json"))
    m.add_argument("--min-size", type=int, default=20)
    m.add_argument("--top", type=int, default=8)
    m.set_defaults(fn=cmd_match)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
