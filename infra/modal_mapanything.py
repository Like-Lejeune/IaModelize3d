"""MapAnything (Apache-2.0 checkpoint) as a GPU web endpoint on Modal.

Deploy:  modal deploy infra/modal_mapanything.py
Then set FW_MAPANYTHING_URL to the printed URL (and FW_MAPANYTHING_TOKEN if you add auth).

The inference call follows the MapAnything README (`MapAnything.from_pretrained`,
`model.infer(views, ...)`); check it against the version you install.
"""
import base64
import io

import modal

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git", "libgl1", "libglib2.0-0")
    .pip_install("torch", "torchvision", "pillow", "numpy", "fastapi[standard]")
    .pip_install("git+https://github.com/facebookresearch/map-anything.git")
)
app = modal.App("formwright-mapanything", image=image)
CHECKPOINT = "facebook/map-anything-apache"


@app.cls(gpu="L4", scaledown_window=300, timeout=900)
class MapAnything:
    @modal.enter()
    def load(self):
        import torch
        from mapanything.models import MapAnything as Model

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = Model.from_pretrained(CHECKPOINT).to(self.device).eval()

    @modal.fastapi_endpoint(method="POST")
    def reconstruct(self, body: dict):
        import tempfile
        from pathlib import Path

        import numpy as np
        import torch
        from mapanything.utils.image import load_images
        from PIL import Image

        with tempfile.TemporaryDirectory() as d:
            ids = []
            for i, item in enumerate(body["images"]):
                Image.open(io.BytesIO(base64.b64decode(item["jpeg"]))).convert("RGB").save(Path(d) / f"{i:03d}.jpg")
                ids.append(item["id"])
            views = load_images(d)
            with torch.no_grad():
                preds = self.model.infer(views, memory_efficient_inference=False, use_amp=True, amp_dtype="bf16",
                                         apply_mask=True, mask_edges=True)
        out_views, points = [], []
        for aid, p in zip(ids, preds):
            pose = p["camera_poses"][0].float().cpu().numpy()
            K = p["intrinsics"][0].float().cpu().numpy()
            pts = p["pts3d"][0].float().cpu().numpy().reshape(-1, 3)
            mask = p.get("mask")
            if mask is not None:
                pts = pts[mask[0].cpu().numpy().reshape(-1) > 0]
            step = max(1, len(pts) // 20000)
            points.append(pts[::step])
            out_views.append({"asset_id": aid, "pose": pose.tolist(), "intrinsics": K.tolist()})
        allp = np.concatenate(points) if points else np.zeros((0, 3))
        return {"views": out_views, "points": allp.round(5).tolist(), "units": "m"}
