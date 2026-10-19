"""Fine-tune Nemotron 3 Diarization on the owner's corrected episodes (owner, 2026-10-19).

Runs in D:\\venvs\\nemo312 (Python 3.12, like nemotron_diarize.py), from the manifests that
nemotron_finetune_data.py writes. Windows has no triton, so flex_attention runs eager; data loads
in the main process (num_workers 0). Saves a .nemo that nemotron_diarize.py loads through
NEMOTRON_MODEL.

  D:\\venvs\\nemo312\\Scripts\\python.exe scripts/nemotron_finetune.py --hold ep68 [--steps 400] [--lr 1e-5]
"""
import argparse
import os
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "0")
import lightning.pytorch as pl  # noqa: E402
import torch  # noqa: E402
from nemo.collections.asr.models import SortformerEncLabelModel  # noqa: E402
from nemo.collections.asr.modules import transformer_encoder_utils as TU  # noqa: E402
from omegaconf import OmegaConf, open_dict  # noqa: E402
from torch.nn.attention.flex_attention import flex_attention  # noqa: E402

TU._get_flex_attention = lambda x: flex_attention
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "_finetune"


class Losses(pl.Callback):
    """Print the training loss every 20 steps and the validation loss, so a run can be read."""
    def on_train_batch_end(self, trainer, module, outputs, batch, i):
        if trainer.global_step % 20 == 0:
            loss = outputs["loss"] if isinstance(outputs, dict) else outputs
            print(f"step {trainer.global_step} train_loss {float(loss):.4f}", flush=True)

    def on_validation_end(self, trainer, module):
        print(f"step {trainer.global_step} " + " ".join(f"{k} {float(v):.4f}" for k, v in
              trainer.callback_metrics.items() if k.startswith("val")), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", default="ep68")
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--lr", type=float, default=1e-5)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--out", default=r"D:\venvs\models")
    a = ap.parse_args()

    m = SortformerEncLabelModel.from_pretrained("nvidia/Nemotron-3-Diarization")
    with open_dict(m.cfg):
        for key, name in (("train_ds", "train"), ("validation_ds", "val")):
            c = m.cfg[key]
            c.manifest_filepath = str(DATA / f"{name}_hold_{a.hold}.json")
            c.batch_size, c.num_workers, c.pin_memory = a.batch, 0, False
            c.session_len_sec = 90
            if "subsegment_mode" in c:
                c.subsegment_mode = False
        m.cfg.optim.lr = a.lr
        m.cfg.optim.sched = OmegaConf.create({"name": "CosineAnnealing", "warmup_steps": 20,
                                              "min_lr": a.lr / 10, "max_steps": a.steps})
    m.setup_training_data(m.cfg.train_ds)
    m.setup_validation_data(m.cfg.validation_ds)
    m.setup_optimization(m.cfg.optim)

    trainer = pl.Trainer(accelerator="gpu", devices=1, max_steps=a.steps, precision=32,
                         val_check_interval=50, check_val_every_n_epoch=None, limit_val_batches=30,
                         log_every_n_steps=10, enable_checkpointing=False, logger=False,
                         gradient_clip_val=1.0, num_sanity_val_steps=0,
                         callbacks=[Losses()], enable_progress_bar=False)
    m.set_trainer(trainer)
    trainer.fit(m)
    Path(a.out).mkdir(parents=True, exist_ok=True)
    out = Path(a.out) / f"nemotron_ft_hold_{a.hold}_s{a.steps}.nemo"
    m.save_to(str(out))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
