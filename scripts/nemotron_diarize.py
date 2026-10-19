"""NVIDIA Nemotron 3 Diarization on one 16 kHz mono wav; saves per-speaker activity every 10 ms.

Runs in its OWN Python 3.12 environment (NeMo does not support 3.14), by default
D:\\venvs\\nemo312; voice_label_raw.py calls it there. NeMo must be 3.1 or newer (3.0.0 lacks
the model's `rope` attention).

  D:\\venvs\\nemo312\\Scripts\\python.exe scripts/nemotron_diarize.py <in.wav> <out.npz>

Two Windows workarounds: the eager flex_attention (Windows has no triton for the compiled
kernel), and the audio passed as an array (NeMo's temporary manifest cannot be deleted while
open on Windows).
"""
import os
import sys

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402
import torch  # noqa: E402
from nemo.collections.asr.models import SortformerEncLabelModel  # noqa: E402
from nemo.collections.asr.modules import transformer_encoder_utils as TU  # noqa: E402
from torch.nn.attention.flex_attention import flex_attention  # noqa: E402

TU._get_flex_attention = lambda x: flex_attention

wav, out = sys.argv[1], sys.argv[2]
model = os.environ.get("NEMOTRON_MODEL")       # a fine-tuned .nemo (nemotron_finetune.py), for tests
m = (SortformerEncLabelModel.restore_from(model) if model
     else SortformerEncLabelModel.from_pretrained("nvidia/Nemotron-3-Diarization"))
m.eval()
s = m.sortformer_modules                     # the model card's offline preset
s.spkcache_len, s.fifo_len, s.chunk_len, s.chunk_right_context, s.spkcache_update_period = 264, 40, 340, 40, 300
m._check_streaming_parameters()
audio, sr = sf.read(wav, dtype="float32")
with torch.inference_mode():
    segs, probs = m.diarize(audio=[audio], batch_size=1, sample_rate=sr, include_tensor_outputs=True)
p = probs[0]
p = (p.float().cpu().numpy() if hasattr(p, "cpu") else np.asarray(p)).reshape(-1, 8)
np.savez(out, probs=p)
print(f"nemotron: {len(p)} frames of 10 ms, {len(segs[0])} segments")
