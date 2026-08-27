"""Trim setup/running out of both READMEs, leaving a pointer to ARCHITECTURE.md."""
import re
from pathlib import Path

NL = chr(10)

EN_TAIL = """## Reproducing this

The whole pipeline is in `scripts/`, and everything you need to run it -- the stack,
one-time setup, commands, and how the output is verified -- is in
[ARCHITECTURE.md](ARCHITECTURE.md). Every failure that shaped it is logged in
[ENGINEERING_LOG.md](ENGINEERING_LOG.md).
"""

MS_TAIL = """## Menghasilkan semula arkib ini

Keseluruhan pipeline ada dalam `scripts/`, dan segala yang diperlukan untuk
menjalankannya -- teknologi yang digunakan, persediaan sekali sahaja, arahan, dan cara
hasilnya disahkan -- ada dalam [ARCHITECTURE.md](ARCHITECTURE.md) (dalam Bahasa
Inggeris). Setiap kegagalan yang membentuk pipeline ini direkodkan dalam
[ENGINEERING_LOG.md](ENGINEERING_LOG.md) (dalam Bahasa Inggeris).
"""

for path, tail, arch_line, log_line in [
    ("README.md", EN_TAIL,
     "ARCHITECTURE.md                          # the stack: setup, commands, verification",
     "ENGINEERING_LOG.md                       # every failure found, its cause and fix"),
    ("README.ms.md", MS_TAIL,
     "ARCHITECTURE.md                          # teknologi: persediaan, arahan, pengesahan",
     "ENGINEERING_LOG.md                       # setiap kegagalan, puncanya dan pembetulannya"),
]:
    p = Path(path)
    t = p.read_text(encoding="utf-8")

    # 1. drop everything from the "## Pipeline" heading onward, replace with the pointer
    i = t.find(NL + "## Pipeline")
    assert i > 0, f"no Pipeline heading in {path}"
    t = t[:i].rstrip() + NL * 2 + tail

    # 2. refresh the structure listing
    t = re.sub(r"^ARCHITECTURE\.md .*$", arch_line, t, count=1, flags=re.M)
    if "ENGINEERING_LOG.md" not in t:
        t = t.replace(arch_line, arch_line + NL + log_line, 1)

    p.write_text(t.rstrip() + NL, encoding="utf-8")
    print(f"{path}: {len(t.split(NL))} lines")
