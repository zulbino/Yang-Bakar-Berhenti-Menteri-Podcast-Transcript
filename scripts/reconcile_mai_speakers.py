"""Join up MAI's per-chunk speaker numbers into one set of names, then write raw.md.

WHY THIS EXISTS. `transcribe_mai.py` cuts long episodes into 30-minute chunks because the
Azure diarization sub-service 503s above roughly half an hour. Speaker numbers are assigned
PER REQUEST, so chunk 3's `speaker 0` has nothing to do with chunk 0's. Eight chunks of a
four-hour episode arrive as up to sixteen unrelated clusters, and writing them out as
`Speaker 1` and `Speaker 2` would file several people under two labels while every checker
in the repo read the file as fine. That is why the transcriber refuses to write raw.md for a
chunked run and hands the job here.

HOW IT DECIDES. Two passes over speaker embeddings, no transcript involved:

1. **Continuity.** Every cluster is embedded from its own speech, then clusters are grouped
   across chunks by cosine similarity, single-link, with one hard constraint: two clusters
   from the SAME chunk never merge, because MAI already ruled they are different people.
2. **Naming.** Each group is scored against the cast voiceprints from
   `verify_speaker_voiceprint.py` -- Rafizi, Haziq, Farhan, built from episodes whose labels
   are trusted. A group that wins clearly takes that name. A group that scores below 0.50
   against all three is a guest and keeps a number.

WHAT THE NUMBERS MEAN, and read the printed matrix rather than trusting the grouping. On
this corpus the same person across different recordings scores about 0.93, correct labels
land 0.94-0.97, and different people land 0.30-0.50, so a 0.70 grouping threshold sits in
empty space. Two things still bend it: a cluster made of short interjections has its score
dragged toward whoever surrounds it (ep51's Haziq reads 0.635 and is correct), and a co-host
reference built from interjections reads high against Rafizi. So the group table prints
every score and the weakest link inside each group. A group whose internal link is barely
over the threshold is a chain, not a person.

Unlike the block-span version of this check, the spans here are real speech: MAI gives each
phrase an offset and a duration, so a span does not run to the next block and does not bleed
into the next speaker.

Usage:
    python scripts/reconcile_mai_speakers.py 0M5hweswMpE --out data/_mai_0M5hweswMpE
    python scripts/reconcile_mai_speakers.py 0M5hweswMpE --threshold 0.75
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import common  # noqa: E402
import transcribe_mai as M  # noqa: E402
import verify_speaker_voiceprint as V  # noqa: E402

GROUP_THRESHOLD = 0.70
# Same rules as verify_speaker_voiceprint.score_episode, so a name means the same thing here
# as it does there.
NAME_FLOOR = 0.55
NAME_MARGIN = 0.10
GUEST_CEILING = 0.50
MIN_SPAN_SECONDS = 2.0


def clusters_of(turns):
    """Real speech spans per (chunk, speaker), in seconds."""
    spans = {}
    for turn in turns:
        if turn["speaker"] is None or turn["offset_ms"] is None or turn["end_ms"] is None:
            continue
        start, end = turn["offset_ms"] / 1000, turn["end_ms"] / 1000
        if end - start < MIN_SPAN_SECONDS:
            continue
        spans.setdefault((turn["chunk"], turn["speaker"]), []).append((start, end))
    return spans


def group(keys, vectors, threshold):
    """Single-link grouping across chunks. Two clusters in one chunk can never merge."""
    parent = {k: k for k in keys}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    members = {k: [k] for k in keys}
    pairs = [(float(np.dot(vectors[a], vectors[b])), a, b)
             for i, a in enumerate(keys) for b in keys[i + 1:] if a[0] != b[0]]
    for score, a, b in sorted(pairs, reverse=True):
        if score < threshold:
            break
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        if {m[0] for m in members[ra]} & {m[0] for m in members[rb]}:
            continue  # same chunk on both sides: MAI already said these are two people
        parent[rb] = ra
        members[ra] = members[ra] + members[rb]

    groups = {}
    for k in keys:
        groups.setdefault(find(k), []).append(k)
    return [sorted(v) for v in groups.values()], pairs


def score_against(members, vectors, minutes, references):
    weights = np.array([minutes[k] for k in members])
    mean = np.average([vectors[k] for k in members], axis=0, weights=weights)
    mean = mean / np.linalg.norm(mean)
    scores = {who: float(np.dot(mean, ref)) for who, ref in references.items()}
    internal = min((float(np.dot(vectors[a], vectors[b]))
                    for i, a in enumerate(members) for b in members[i + 1:]), default=None)
    return scores, internal


def name_groups(groups, vectors, minutes, references):
    """Score each group against the cast, biggest group first, then join groups that came
    back with the same name.

    Groups have to be joined afterwards because the same-chunk constraint can force a
    person apart: MAI split Rafizi into two clusters inside ep62's chunk 6, and no amount
    of similarity may merge two clusters of one chunk, so his 207 minutes arrived as two
    groups scoring 0.962 and 0.939 against his reference. One name, one person.
    """
    ordered = sorted(groups, key=lambda g: -sum(minutes[k] for k in g))
    labels, spare = [], 0
    for members in ordered:
        scores, _ = score_against(members, vectors, minutes, references)
        best = max(scores, key=scores.get)
        runner_up = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0
        if scores[best] >= NAME_FLOOR and scores[best] - runner_up >= NAME_MARGIN:
            labels.append((best, f"-> {best}", members))
        elif max(scores.values()) < GUEST_CEILING:
            spare += 1
            labels.append((f"Speaker {spare}", "-> not a known speaker (guest)", members))
        else:
            spare += 1
            labels.append((f"Speaker {spare}", "-> INCONCLUSIVE, left as a number", members))

    joined = {}
    for label, verdict, members in labels:
        entry = joined.setdefault(label, {"verdict": verdict, "members": [], "groups": 0})
        entry["members"].extend(members)
        entry["groups"] += 1

    named, report = {}, []
    for label, entry in sorted(joined.items(), key=lambda kv: -sum(minutes[k]
                                                                   for k in kv[1]["members"])):
        members = sorted(entry["members"])
        scores, internal = score_against(members, vectors, minutes, references)
        for key in members:
            named[key] = label
        report.append({
            "label": label,
            "members": [f"c{c}s{s}" for c, s in members],
            "mai_groups_joined": entry["groups"],
            "minutes": round(sum(minutes[k] for k in members), 1),
            "weakest_internal_link": round(internal, 3) if internal is not None else None,
            "scores": {who: round(score, 3) for who, score in scores.items()},
            "verdict": entry["verdict"],
        })
    return named, report


def relabelled_turns(turns, named):
    """Apply the names, then merge neighbours that now share one -- which is exactly what a
    chunk boundary cutting through a turn looks like once the two sides are named."""
    out = []
    for turn in turns:
        label = named.get((turn["chunk"], turn["speaker"]))
        if label is None:
            # Never grouped, because every one of its turns is under the 2s the embedder
            # needs. On ep62 that is 49 turns of "Hmm." and "Yeah." out of 1669. A cluster
            # id in raw.md would be worse than an admitted unknown -- nine episodes already
            # shipped diarizer ids that way -- and the repo's own convention for a turn
            # with no speaker is this.
            label = "Speaker ?"
        if out and out[-1]["label"] == label:
            out[-1]["text"] += " " + turn["text"]
            continue
        out.append({"label": label, "offset_ms": turn["offset_ms"], "text": turn["text"]})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video_id")
    ap.add_argument("--out", help="sandbox dir, defaults to data/_mai_<video_id>")
    ap.add_argument("--threshold", type=float, default=GROUP_THRESHOLD)
    ap.add_argument("--matrix", action="store_true",
                    help="print every cross-chunk cluster similarity, not just the groups")
    args = ap.parse_args()

    out_dir = Path(args.out) if args.out else M.SANDBOX / f"_mai_{args.video_id}"
    phrases_path = out_dir / "mai_phrases.json"
    if not phrases_path.exists():
        sys.exit(f"{phrases_path} not found -- run transcribe_mai.py first")
    data = json.loads(phrases_path.read_text(encoding="utf-8"))
    turns = data["turns"]

    spans = clusters_of(turns)
    if not spans:
        sys.exit("no usable spans -- every turn is missing offsets or shorter than "
                 f"{MIN_SPAN_SECONDS}s")

    audio = V.load_audio(args.video_id)
    keys = sorted(spans)
    minutes = {k: sum(e - s for s, e in spans[k]) / 60 for k in keys}
    print(f"{len(keys)} clusters over {len({k[0] for k in keys})} chunks")

    vectors = {}
    for key in keys:
        vector = V.embed(audio, spans[key])
        if vector is None:
            print(f"  c{key[0]}s{key[1]}: no embeddable clip, dropped")
            continue
        vectors[key] = vector
        print(f"  c{key[0]}s{key[1]}  {minutes[key]:6.1f} min  {len(spans[key])} turns")
    keys = [k for k in keys if k in vectors]

    references = V.build_references(V.DEFAULT_REFERENCES)
    groups, pairs = group(keys, vectors, args.threshold)
    named, report = name_groups(groups, vectors, minutes, references)

    if args.matrix:
        print("\ncross-chunk cluster similarity")
        for score, a, b in sorted(pairs, reverse=True):
            print(f"  c{a[0]}s{a[1]} ~ c{b[0]}s{b[1]}  {score:+.3f}")

    print(f"\n{len(report)} group(s) at threshold {args.threshold}")
    for row in report:
        scores = "  ".join(f"{who.split()[0]}={s:+.3f}" for who, s in row["scores"].items())
        link = ("n/a" if row["weakest_internal_link"] is None
                else f"{row['weakest_internal_link']:+.3f}")
        print(f"  {row['label']:12} {row['minutes']:6.1f} min  weakest link {link}  "
              f"{scores}   {row['verdict']}"
              + (f"  [{row['mai_groups_joined']} MAI groups joined]"
                 if row["mai_groups_joined"] > 1 else ""))
        print(f"               {' '.join(row['members'])}")

    final = relabelled_turns(turns, named)
    labels = sorted({t["label"] for t in final})
    unknown = [t for t in final if t["label"] == "Speaker ?"]
    if len(labels) < M.MIN_SPEAKERS:
        sys.exit(f"\nREFUSING to write: everything collapsed into {labels}. Either the "
                 f"threshold is too low or the grouping chained -- rerun with --matrix.")

    reconcile = {"threshold": args.threshold, "groups": report,
                 "turns_in": len(turns), "turns_out": len(final),
                 "unknown_turns": len(unknown),
                 "unknown_chars": sum(len(t["text"]) for t in unknown),
                 "labels": labels}
    (out_dir / "reconcile.json").write_text(json.dumps(reconcile, indent=1), encoding="utf-8")

    import transcribe_episode as T

    episode = T.load_episode(args.video_id)
    body = ["# Raw Transcript", ""]
    for turn in final:
        body.append(f"{M.stamp(turn['offset_ms'])} {turn['label']}: {turn['text']}")
        body.append("")

    unresolved = [row["label"] for row in report if "INCONCLUSIVE" in row["verdict"]]
    fields = {
        **T.episode_common_fields(episode),
        "model": f"microsoft/{M.MODEL}",
        "note": (f"Raw transcript from {M.MODEL} via the Azure Speech API, verbatim style, "
                 f"with word-level timestamps from the model itself rather than from chunk "
                 f"boundaries. The audio was sent in {data['chunk_seconds'] // 60}-minute "
                 f"chunks because diarization fails above roughly half an hour, so MAI's "
                 f"per-request speaker numbers were joined across chunks by voiceprint "
                 f"similarity and named against the cast references at threshold "
                 f"{args.threshold}. See reconcile.json for every score."),
    }
    raw_md = out_dir / "raw.md"
    raw_md.write_text(common.frontmatter_md(fields, "\n".join(body)), encoding="utf-8")
    print(f"\nwrote {raw_md}  ({len(final)} turns, labels {labels})")
    if unknown:
        print(f"{len(unknown)} turns ({sum(len(t['text']) for t in unknown)} chars) are "
              f"'Speaker ?': every turn in their cluster is under {MIN_SPAN_SECONDS}s, which "
              f"is below what the embedder can score.")
    if unresolved:
        print(f"NOT NAMED: {unresolved} -- scored between guest and cast. Check the video "
              f"before adopting these.")
    print("SANDBOX ONLY. Compare it against the current pipeline before it goes near "
          "episodes/.")


if __name__ == "__main__":
    main()
