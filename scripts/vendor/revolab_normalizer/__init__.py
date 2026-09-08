"""Vendored Malay text normalizer from the Revolab Malaysian ASR benchmark.

Source: https://github.com/Revolab-Sdn-Bhd/revolab-asr-benchmark
Vendored 2026-09-08 at commit HEAD of main, unmodified, under the MIT licence
reproduced in LICENSE alongside this file.

WHY IT IS HERE AND NOT A DEPENDENCY. It is two files of pure standard library, and it
encodes something this corpus needs and nothing else provides: a curated map of Malaysian
Malay spelling variants to one canonical form, so `okay`/`okey`/`oke` or `jugak`/`juga`
stop being counted as transcription errors. Without it, any word error rate computed over
this corpus mostly measures spelling convention.
"""
from .basic import BasicTextNormalizer
from .malay import MalayTextNormalizer

__all__ = ["BasicTextNormalizer", "MalayTextNormalizer"]
