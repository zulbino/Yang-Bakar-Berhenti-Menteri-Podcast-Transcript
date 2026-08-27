"""Reproduce the 1.22 re-emission failure against the guard."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import types as _t, importlib.util
spec = importlib.util.spec_from_file_location("lg", Path(__file__).parent / "lib_gemini.py")
# import without the google-genai dependency chain if it is unavailable
try:
    import lib_gemini as lg
except Exception as e:
    print("import failed:", e); raise SystemExit(1)

d = lg._drop_reemitted_prefix
ok = True
def check(name, got, want):
    global ok
    status = "PASS" if got == want else "FAIL"
    if got != want: ok = False
    print(f"  [{status}] {name}\n         got  {got!r}\n         want {want!r}")

# 1. Plain continuation, nothing repeated -> appended untouched.
check("clean continuation",
      d("[00:01] A: hello there\n\n[00:10] B: yes indeed\n\n", "[00:20] A: next point\n\n"),
      ("[00:01] A: hello there\n\n[00:10] B: yes indeed\n\n[00:20] A: next point\n\n", 0))

# 2. The ep45 signature: model backtracks and re-emits covered turns under
#    fresh timestamps, then continues.
check("re-emission under fresh timestamps",
      d("[00:01] A: hello there\n\n[00:10] B: yes indeed\n\n[00:20] A: third turn\n\n",
        "[00:30] A: hello there\n\n[00:40] B: yes indeed\n\n[00:50] A: brand new\n\n"),
      ("[00:01] A: hello there\n\n[00:10] B: yes indeed\n\n[00:20] A: third turn\n\n[00:50] A: brand new\n\n", 2))

# 3. Whole round is re-emission -> no growth, so the loop's progress test fires.
full = "[00:01] A: hello there\n\n[00:10] B: yes indeed\n\n"
out, dropped = d(full, "[00:30] A: hello there\n\n")
print(f"  [{'PASS' if len(out) <= len(full) else 'FAIL'}] total re-emission makes no progress "
      f"(len {len(full)} -> {len(out)}, dropped {dropped})")
ok &= len(out) <= len(full)

# 4. A turn cut mid-sentence by MAX_TOKENS and restated in full is not glued.
check("mid-turn cut restated in full",
      d("[00:01] A: hello there\n\n[00:10] B: this sentence was cut off right in the mid",
        "[00:10] B: this sentence was cut off right in the middle of things\n\n[00:20] A: onward\n\n"),
      ("[00:01] A: hello there\n\n[00:10] B: this sentence was cut off right in the middle of things\n\n[00:20] A: onward\n\n", 0))

# 5. Genuine repeated speech LATER in the chunk survives (memory: real Malay
#    speech repeats -- only the prefix may be stripped).
check("genuine later repetition preserved",
      d("[00:01] A: jadi jadi\n\n", "[00:10] B: betul\n\n[00:20] A: jadi jadi\n\n"),
      ("[00:01] A: jadi jadi\n\n[00:10] B: betul\n\n[00:20] A: jadi jadi\n\n", 0))

print("\nALL PASS" if ok else "\nFAILURES PRESENT")
raise SystemExit(0 if ok else 1)
