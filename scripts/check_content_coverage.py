"""Does a transcript cover the whole episode, measured PER TIME WINDOW against the captions?

THE GAP THIS CLOSES. Three separate checks passed gemini-3.8-flash's ep62 transcript while
its last 30 minutes -- 12.8% of a 3h55m episode, 3,003 caption words of substantive content
-- were absent:

  duplicate share   0.0%     (no loop, unlike ep61's 92%)
  stamp coverage  100.0%     the model wrote "[3:55:22] [end of audio]" itself
  word ratio        1.10x    against the ms-orig caption track, whole-file

The word ratio is the interesting failure. Over the 87% it DID cover, the model emitted 26%
more words than YouTube's caption ASR, which is normal -- captions drop words. That excess
numerically cancelled the missing 13%, so the whole-file ratio looked healthy. **A whole-file
word count cannot see a truncation, because verbosity elsewhere pays for it.** Bin by time
and the hole is obvious.

It also wrote a plausible sign-off where the hosts were mid-sentence about a company filing,
so nothing in the TEXT looks wrong either. Only the clock-versus-content comparison finds it.

The captions are the right yardstick here for the same reason they anchor every timing check
in this repo: they are independently produced, they are not what any engine under test
generated, and they carry per-word timings. They are also lossy, which is why this reports a
RATIO per window and flags only windows that fall far below the file's own median rather
than expecting parity.

  python scripts/check_content_coverage.py ep62
  python scripts/check_content_coverage.py --raw data/_gem38_0M5hweswMpE/raw.md ep62
  python scripts/check_content_coverage.py --all
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "audio"

WINDOW_S = 300              # 5 minutes: long enough to smooth a pause, short enough to localise
EMPTY_RATIO = 0.15          # under 15% of the caption words in a window is a hole
MIN_CAPTION_WORDS = 40      # below this the window is silence/music, not evidence of loss

BLOCK_RE = re.compile(r"^\[([\d:]+)\]\s*([^:\n]{0,40}?):\s*(.*)$", re.M)
CAPTION_WORD_RE = re.compile(r"<(\d{2}):(\d{2}):(\d{2})\.\d{3}><c>\s*([^<]+)</c>")


def to_seconds(stamp):
    parts = [int(p) for p in stamp.split(":")]
    return sum(v * 60 ** i for i, v in enumerate(reversed(parts)))


CUE_START_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.\d{3}\s+-->", re.M)
SPEAKER_MARK_RE = re.compile(r"&gt;&gt;|>>")


def parse_caption_words(text):
    """(seconds, word) for every caption word in a YouTube auto-caption track.

    THE BUG THIS REPLACES. The old version matched only words wrapped in
    `<HH:MM:SS.mmm><c>word</c>`, which is every word in a cue EXCEPT the first -- YouTube
    puts no inline timestamp before a cue's opening word. On ep62 that silently dropped
    5,142 of 28,509 caption words, 18% of the track. Because it dropped them uniformly, the
    whole-file word ratio came out at a consistent 1.11-1.12 for every episode in the
    corpus, and that consistency read as evidence the measure was sound. It was measuring
    the parser. ep62's real ratio is 0.92: the local ASR produces FEWER words than the
    caption track, not 12% more.

    Two further details the old regex missed. `&gt;&gt;` is YouTube's speaker-change
    marker, not speech, and counting it as a word adds about 5%. And a cue carrying no
    inline timings is usually the settled repeat of the cue before it, so its words are
    deduplicated against what has already been emitted rather than counted twice -- but
    only the repeated prefix, because short interjections arrive as plain cues that carry
    real content and nothing else records them.
    """
    out, tail = [], []
    for cue in text.split("\n\n"):
        start_match = CUE_START_RE.search(cue)
        if not start_match:
            continue
        start = to_seconds(":".join(start_match.group(1, 2, 3)))
        body = [line for line in cue.split("\n") if "-->" not in line and line.strip()]
        if not body:
            continue
        line = body[-1]
        stamped = []
        for h, m, s, chunk in CAPTION_WORD_RE.findall(line):
            stamped += [(to_seconds(f"{h}:{m}:{s}"), w) for w in chunk.split()]
        if stamped:
            head = SPEAKER_MARK_RE.sub(" ", line.split("<", 1)[0]).split()
            cue_words = [(start, w) for w in head] + stamped
        else:
            plain = SPEAKER_MARK_RE.sub(" ", re.sub(r"<[^>]+>", "", line)).split()
            cue_words = [(start, w) for w in plain]
        words_only = [w for _, w in cue_words]
        overlap = 0
        for size in range(min(len(words_only), len(tail)), 0, -1):
            if tail[-size:] == words_only[:size]:
                overlap = size
                break
        out.extend(cue_words[overlap:])
        tail = [w for _, w in out[-40:]]
    return out


def caption_words(video_id):
    """Per-word timings from the ms-orig track, falling back to ms then en."""
    for lang in ("ms-orig", "ms", "en"):
        path = AUDIO_DIR / f"{video_id}.{lang}.vtt"
        if path.exists():
            words = parse_caption_words(path.read_text(encoding="utf-8"))
            if words:
                return words, lang
    return [], None


def transcript_words(raw_path, runtime_s):
    """(start, end, word_count) per block, so words spread over the span they were SPOKEN in.

    The first version of this assigned every block's words to its start stamp, and the
    control caught it: ep61's owner-reviewed raw.md came back with six "empty" windows over
    17.2% of its runtime. Nothing was missing. This corpus has blocks spanning minutes --
    one ep62 block covers 896s of speech -- so charging all of a long block's words to its
    first second leaves every later window looking empty. A checker whose false-positive
    rate scales with block length is worse than no checker, because this corpus's real
    defect is long blocks.

    So a block owns the interval from its own stamp to the next block's stamp, and its words
    spread evenly across it. That is still an approximation, but it is unbiased with respect
    to block length, which is the property that matters.
    """
    body = raw_path.read_text(encoding="utf-8")
    if "# Raw Transcript" in body:
        body = body.split("# Raw Transcript", 1)[1]
    blocks = [(to_seconds(stamp), len(text.split()))
              for stamp, _label, text in BLOCK_RE.findall(body)]
    out = []
    for i, (start, count) in enumerate(blocks):
        end = blocks[i + 1][0] if i + 1 < len(blocks) else runtime_s
        out.append((start, max(end, start + 1), count))
    return out


def coverage(raw_path, video_id, runtime_s):
    caps, lang = caption_words(video_id)
    if not caps:
        return None
    blocks = transcript_words(raw_path, runtime_s)
    if not blocks:
        return None

    n = int(runtime_s // WINDOW_S) + 1
    cap_bins, txt_bins = [0] * n, [0.0] * n
    for t, _w in caps:
        if t // WINDOW_S < n:
            cap_bins[int(t // WINDOW_S)] += 1
    for start, end, count in blocks:
        span = end - start
        for i in range(int(start // WINDOW_S), min(int((end - 1) // WINDOW_S) + 1, n)):
            lo, hi = max(start, i * WINDOW_S), min(end, (i + 1) * WINDOW_S)
            if hi > lo:
                txt_bins[i] += count * (hi - lo) / span

    holes = []
    for i in range(n):
        if cap_bins[i] < MIN_CAPTION_WORDS:
            continue
        ratio = txt_bins[i] / cap_bins[i]
        if ratio < EMPTY_RATIO:
            holes.append({"window_start_s": i * WINDOW_S,
                          "caption_words": cap_bins[i],
                          "transcript_words": txt_bins[i],
                          "ratio": ratio})
    return {
        "caption_lang": lang,
        "caption_words": sum(cap_bins),
        "transcript_words": sum(txt_bins),
        "whole_file_ratio": (sum(txt_bins) / sum(cap_bins)) if sum(cap_bins) else None,
        "windows": n,
        "holes": holes,
        "hole_seconds": len(holes) * WINDOW_S,
        "hole_share": len(holes) * WINDOW_S / runtime_s if runtime_s else 0,
    }


def human(seconds):
    seconds = int(seconds)
    return f"{seconds//3600}h{seconds%3600//60:02d}m"


def report(tag, result, runtime_s):
    if result is None:
        print(f"{tag}: no captions cached, or no parseable blocks -- NOT CHECKED")
        return False
    r = result
    print(f"{tag}")
    print(f"  captions ({r['caption_lang']}) {r['caption_words']:,} words   "
          f"transcript {r['transcript_words']:,.0f} words   "
          f"whole-file ratio {r['whole_file_ratio']:.2f}")
    if not r["holes"]:
        print(f"  no empty windows across {r['windows']} x {WINDOW_S}s -- coverage OK")
        return True
    print(f"  {len(r['holes'])} EMPTY WINDOW(S), {human(r['hole_seconds'])} "
          f"({r['hole_share']:.1%} of runtime):")
    for h in r["holes"]:
        print(f"    {human(h['window_start_s'])}  captions {h['caption_words']:4d} words, "
              f"transcript {h['transcript_words']:4.0f}  ratio {h['ratio']:.2f}")
    print(f"  NOTE the whole-file ratio above is {r['whole_file_ratio']:.2f} -- verbosity in "
          f"the covered part pays for the hole, which is why that number cannot be trusted "
          f"on its own.")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode", nargs="?", help="epNN or video_id")
    ap.add_argument("--raw", help="check this transcript instead of the episode's raw.md")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    import json

    from common import episode_path, resolve_tag

    manifest = json.loads((ROOT / "data/manifest.json").read_text(encoding="utf-8"))

    if args.all:
        ok = True
        for path in sorted(ROOT.glob("episodes/*/*/raw.md")):
            vid = None
            head = path.read_text(encoding="utf-8")[:800]
            m = re.search(r"^video_id:\s*(\S+)", head, re.M)
            if m:
                vid = m.group(1)
            row = next((e for e in manifest if e["video_id"] == vid), None)
            if not row:
                continue
            ok &= report(path.parent.name[:60],
                         coverage(path, vid, row["duration_seconds"]), row["duration_seconds"])
        sys.exit(0 if ok else 1)

    if not args.episode:
        ap.error("give an episode, or --all")
    episode = resolve_tag(manifest, args.episode)
    vid, runtime = episode["video_id"], episode["duration_seconds"]
    raw_path = (Path(args.raw).resolve() if args.raw
                else ROOT / "episodes" / episode_path(episode) / "raw.md")
    if not raw_path.exists():
        sys.exit(f"{raw_path} not found")
    label = raw_path.name if ROOT not in raw_path.parents else str(raw_path.relative_to(ROOT))
    ok = report(label, coverage(raw_path, vid, runtime), runtime)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
