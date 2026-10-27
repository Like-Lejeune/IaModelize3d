"""Serve Meta's open-weights Muse Glimmer (30B, Apache-2.0) on Modal with vLLM.

    modal deploy infra/modal_glimmer.py

Then point Formwright at it (the independent critic runs on open weights):
    FW_OPEN_BASE_URL=https://<workspace>--formwright-glimmer-serve.modal.run/v1
    FW_OPEN_MODEL=meta-models/Muse-Glimmer-30B
    FW_MODEL_CRITIC=meta-models/Muse-Glimmer-30B
"""
import subprocess

import modal

MODEL = "meta-models/Muse-Glimmer-30B"  # bf16 checkpoint, ~60 GB
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("vllm", "huggingface_hub[hf_transfer]")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)
weights = modal.Volume.from_name("glimmer-weights", create_if_missing=True)
app = modal.App("formwright-glimmer")


@app.function(image=image, gpu="H100", volumes={"/models": weights}, timeout=3600, scaledown_window=600, max_containers=1)
@modal.concurrent(max_inputs=16)
@modal.web_server(port=8000, startup_timeout=1200)
def serve():
    subprocess.Popen([
        "vllm", "serve", MODEL,
        "--download-dir", "/models",
        "--max-model-len", "32768",
        "--limit-mm-per-prompt", '{"image": 6}',
        "--host", "0.0.0.0", "--port", "8000",
    ])
