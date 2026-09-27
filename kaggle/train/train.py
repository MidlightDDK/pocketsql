"""Kaggle kernel for one PocketSQL training run (`kaggle kernels push -p kaggle/train`).

Self-contained: pinned installs (the versions in training/pyproject.toml and uv.lock;
torch is the Kaggle image's CUDA build, recorded in summary.json), this public repo's
training code at CODE_REVISION, and the dataset revision pinned in CONFIG. It runs
pocketsql.train.run on one T4 and leaves everything in /kaggle/working/outputs.
kernel-metadata.json's machine_shape "NvidiaTeslaT4" selects GPU T4 x2:
https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels_metadata.md
"""

import io
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

STARTED = time.time()
CODE_REVISION = "661340824035ca3594f19b6b25847a8924ed98b9"
CONFIG = "training/configs/train_v2.yaml"
PINS = [
    "accelerate==1.15.0",
    "datasets==5.0.1",
    "duckdb==1.5.5",
    "huggingface-hub==1.33.0",
    "jinja2==3.1.6",
    "onnx==1.23.0",
    "onnx-ir==1.0.0",
    "onnxruntime==1.30.0",
    "onnxruntime-genai==0.17.0",
    "peft==0.21.0",
    "pyyaml==6.0.3",
    "safetensors==0.8.0",
    "sqlglot==30.19.0",
    "tokenizers==0.23.2",
    "transformers==5.17.0",
    "trl==1.14.0",
]

# Unverified Kaggle accounts get silently neither GPU nor internet: fail fast.
if not shutil.which("nvidia-smi"):
    sys.exit("no GPU attached (is the Kaggle account phone-verified?)")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", *PINS], check=True)
# PEFT raises on the image's torchao 0.10 (needs > 0.16) when it looks for quantized
# layers; we use neither torchao nor gptqmodel.
pip_rm = [sys.executable, "-m", "pip", "uninstall", "-y", "-q", "torchao", "gptqmodel"]
subprocess.run(pip_rm, check=True)
src = Path("/tmp/pocketsql")
url = f"https://codeload.github.com/MidlightDDK/pocketsql/tar.gz/{CODE_REVISION}"
with (
    urllib.request.urlopen(url) as r,
    tarfile.open(fileobj=io.BytesIO(r.read()), mode="r:gz") as tar,
):
    tar.extractall(src, filter="data")
repo = next(src.iterdir())
env = {
    **os.environ,
    "PYTHONPATH": str(repo / "training" / "src"),
    "CUDA_VISIBLE_DEVICES": "0",  # T4 x2 machine; one GPU keeps the effective batch
}
subprocess.run(
    [
        sys.executable, "-m", "pocketsql.train.run",
        "--config", str(repo / CONFIG),
        "--out", "/kaggle/working/outputs",
        "--work", "/tmp/work",
        "--code-revision", CODE_REVISION,
        "--started", str(STARTED),
    ],
    check=True,
    env=env,
)  # fmt: skip
