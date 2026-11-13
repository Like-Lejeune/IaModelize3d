"""Serve Meta's open-weights Muse Glimmer (30B, Apache-2.0) on Modal with vLLM.

    modal secret create glimmer-api-key VLLM_API_KEY=<a long random string>
    modal deploy infra/modal_glimmer.py

Then point IaModelize3d at it (the independent critic runs on open weights):
    FW_OPEN_BASE_URL=https://<workspace>--iamodelize3d-glimmer-serve.modal.run/v1
    FW_OPEN_API_KEY=<the same string>
    FW_OPEN_MODEL=meta-models/Muse-Glimmer-30B
    FW_MODEL_CRITIC=meta-models/Muse-Glimmer-30B

A cold start loads ~60 GB of weights and can take many minutes, which a live critic call would wait out.
On demo day deploy with `GLIMMER_MIN_CONTAINERS=1 modal deploy infra/modal_glimmer.py` to keep one GPU up
(billed while it runs), and redeploy without it afterwards.
"""
import os
import subprocess

import modal

MODEL = "meta-models/Muse-Glimmer-30B"  # bf16 checkpoint, ~60 GB
MIN_CONTAINERS = int(os.environ.get("GLIMMER_MIN_CONTAINERS", "0"))  # read at deploy time
image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install("vllm", "huggingface_hub[hf_transfer]")
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)
weights = modal.Volume.from_name("glimmer-weights", create_if_missing=True)
app = modal.App("iamodelize3d-glimmer")


@app.function(image=image, gpu="H100", volumes={"/models": weights}, secrets=[modal.Secret.from_name("glimmer-api-key")],
              timeout=3600, scaledown_window=600, min_containers=MIN_CONTAINERS, max_containers=1)
@modal.concurrent(max_inputs=16)
@modal.web_server(port=8000, startup_timeout=1200)
def serve():
    # the endpoint is public; without a key anyone who finds the URL could use the GPU
    subprocess.Popen([
        "vllm", "serve", MODEL,
        "--download-dir", "/models",
        "--max-model-len", "32768",
        "--limit-mm-per-prompt", '{"image": 6}',
        "--api-key", os.environ["VLLM_API_KEY"],
        "--host", "0.0.0.0", "--port", "8000",
    ])
