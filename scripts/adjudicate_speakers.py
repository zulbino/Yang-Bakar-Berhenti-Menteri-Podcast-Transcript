"""One HTML page of every unresolved diarizer cluster turn, linked to the video.

What is left after the tools run out. `verify_speaker_voiceprint.py` refuses any
short-turn cluster by its own rule (0.60-0.80 is unresolvable however many minutes it
totals) and was measurably INVERTED on ep26, scoring Farhan lowest at 0.385 while
Farhan's long-turn cluster in the same episode scored 0.952. `frames_at.py` reads the
speaker off the camera, but only when the director cuts to a single close shot -- ep19's
two turns sit inside wide two-shots at both timestamps, which prove nothing. So these
turns need the owner's ear, and the only thing left worth automating is making them
cheap to listen to.

Each turn gets a YouTube link seeked LEAD seconds early, its own text, and the turn
either side with its label, because that context is what makes the call possible: at
ep19 [2:24:55] a cluster says "Mahdzir Khalid." and Haziq echoes "Mahdzir Khalid. Padang
Terap." four seconds later, and in this show the echo pattern runs one way.

WHY NOT JUST INFER IT FROM THE TEXT. Because that was tried and it was wrong. The ep26
reading "every turn continues mid-sentence into the next Rafizi turn, so it is Rafizi"
misread a seam between two Rafizi turns straddling Farhan's interjection, and the owner's
per-turn answer split two of those blocks across three speakers. Text adjacency does not
carry direction. The page therefore states no guess: it shows what is there and leaves the
column blank.

Answers go back as a JSON map of timestamp -> name, the shape
`data/_ep26_speaker1_map.json` already uses, including its split form for one block
holding more than one speaker.

  python scripts/adjudicate_speakers.py                  # every episode with one
  python scripts/adjudicate_speakers.py ep19 ep53
"""
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_published import PLACEHOLDER_RE
from common import episode_number, episode_path, resolve_tag, show_era_dir

ROOT = Path(__file__).resolve().parent.parent
# Seek this far before the turn. The turn's own first word is the least useful moment to
# land on -- the voice needs a beat of the preceding speech to place, and the camera cut
# lags the speech by about two seconds anyway (frames_at.py's PAD, and the same reason).
LEAD = 6
TURN = re.compile(r"^\[((?:\d+:)?\d+:\d+)\]\s*([^:\n]{1,40}?)\s*:\s*(.*)$")


def to_seconds(stamp):
    parts = [int(p) for p in stamp.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def turns_of(raw_body):
    out = []
    for line in raw_body.splitlines():
        m = TURN.match(line)
        if m:
            out.append((m.group(1), m.group(2), m.group(3)))
    return out


def collect(ep_dir):
    text = (ep_dir / "raw.md").read_text(encoding="utf-8")
    video_id = re.search(r"^video_id:\s*(\S+)", text, re.M)
    title = re.search(r"^title:\s*'?(.*?)'?$", text, re.M)
    body = text.split("---", 2)[2] if text.startswith("---") else text
    all_turns = turns_of(body)
    unresolved = []
    for i, (stamp, label, said) in enumerate(all_turns):
        if not PLACEHOLDER_RE.match(f"[{stamp}] {label}:"):
            continue
        unresolved.append({
            "stamp": stamp,
            "label": label,
            "said": said,
            "prev": all_turns[i - 1] if i else None,
            "next": all_turns[i + 1] if i + 1 < len(all_turns) else None,
            "seek": max(0, to_seconds(stamp) - LEAD),
        })
    return {
        "title": title.group(1) if title else ep_dir.name,
        "video_id": video_id.group(1) if video_id else "",
        "turns": unresolved,
    }


CSS = """
body{font:15px/1.55 -apple-system,Segoe UI,sans-serif;margin:0;background:#f6f6f4;color:#1b1b1b}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 80px}
h1{font-size:22px;margin:0 0 4px}
.sub{color:#5a5a5a;margin:0 0 26px}
h2{font-size:17px;margin:34px 0 2px;padding-top:18px;border-top:2px solid #ddd}
h2 .n{color:#767676;font-weight:400;font-size:14px}
table{border-collapse:collapse;width:100%;margin-top:12px;background:#fff;
      box-shadow:0 1px 2px rgba(0,0,0,.08)}
th,td{text-align:left;vertical-align:top;padding:9px 11px;border-bottom:1px solid #e8e8e8}
th{background:#efefec;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#444}
td.t{white-space:nowrap;font-variant-numeric:tabular-nums}
td.said{font-weight:600}
.ctx{color:#666;font-size:13.5px}
.ctx b{color:#1b1b1b;font-weight:600}
.lbl{display:inline-block;background:#fde8c8;border:1px solid #e8c288;border-radius:3px;
     padding:0 5px;font-size:12.5px;white-space:nowrap}
.ans{background:#fffdf3;min-width:120px}
a{color:#0b57c2}
"""


def render(episodes):
    rows = []
    total = 0
    for tag, ep in episodes:
        if not ep["turns"]:
            continue
        total += len(ep["turns"])
        rows.append(f"<h2>{html.escape(ep['title'])} "
                    f"<span class='n'>&mdash; {tag}, {len(ep['turns'])} turn(s)</span></h2>")
        rows.append("<table><tr><th>listen</th><th>label</th><th>said</th>"
                    "<th>before / after</th><th class='ans'>who?</th></tr>")
        for t in ep["turns"]:
            url = f"https://www.youtube.com/watch?v={ep['video_id']}&t={t['seek']}s"
            ctx = []
            for which, turn in (("&uarr;", t["prev"]), ("&darr;", t["next"])):
                if turn:
                    ctx.append(f"{which} <b>{html.escape(turn[1])}:</b> "
                               f"{html.escape(turn[2][:170])}")
            rows.append(
                f"<tr><td class='t'><a href='{url}' target='_blank'>{t['stamp']}</a></td>"
                f"<td><span class='lbl'>{html.escape(t['label'])}</span></td>"
                f"<td class='said'>{html.escape(t['said'][:220])}</td>"
                f"<td class='ctx'>{'<br>'.join(ctx)}</td>"
                f"<td class='ans'></td></tr>")
        rows.append("</table>")
    head = (f"<h1>Unresolved speaker turns &mdash; {total} across "
            f"{sum(1 for _, e in episodes if e['turns'])} episode(s)</h1>"
            f"<p class='sub'>Each link seeks {LEAD}s before the turn. No guesses are "
            f"printed on purpose &mdash; text adjacency does not carry direction. "
            f"Answers go back as timestamp &rarr; name.</p>")
    return (f"<!doctype html><meta charset='utf-8'><title>Unresolved speakers</title>"
            f"<style>{CSS}</style><div class='wrap'>{head}{''.join(rows)}</div>")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    if args:
        pairs = [(t, ROOT / "episodes" / episode_path(resolve_tag(manifest, t))) for t in args]
    else:
        pairs = []
        for ep in manifest:
            d = ROOT / "episodes" / episode_path(ep)
            if not (d / "raw.md").exists():
                continue
            num = episode_number(ep)
            # Both shows number ep01-ep06, so a bare tag is ambiguous for twelve episodes
            # -- the `resolve_tag` trap that had every tool silently taking index [0].
            show = "bakar" if show_era_dir(ep) == "yang-bakar-menteri" else "berhenti"
            pairs.append((f"ep{num:02d}:{show}" if num is not None else d.name, d))

    episodes = [(tag, collect(d)) for tag, d in pairs]
    out = ROOT / "unresolved_speakers.html"
    out.write_text(render(episodes), encoding="utf-8")
    for tag, ep in episodes:
        if ep["turns"]:
            print(f"  {len(ep['turns']):>3}  {tag:14} {ep['title'][:56]}")
    print(f"\n{sum(len(e['turns']) for _, e in episodes)} unresolved turn(s) -> {out}")


if __name__ == "__main__":
    main()
