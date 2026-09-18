"""A tiny SDXL Turbo service (spec 074 §4).

**This does not run in the cluster.** It runs on the operator's own GPU box,
beside LM Studio, and the platform reaches it the same way it reaches the model
host: over the network, at an address that lives in configuration and never in
this repository.

The contract is deliberately almost nothing — prompt in, PNG out — so the model
behind it can be swapped without the platform knowing:

    POST /generate  {"prompt": str, "seed": int, "steps": int, "model": str}
                 -> image/png, or 422 if the safety check refused it
    GET  /health -> {"ok": true, "model": "...", "gpu": {...}}

Setup is in README.md. Run it with:

    python service.py

Two things it does that the platform cannot:

1. **The NSFW check**, because that is where the GPU already is.
2. **Deterministic seeding**, so a candidate can be reproduced from its seed if
   somebody needs to work out what happened.
"""

import io
import os

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, Response, status
from pydantic import BaseModel, Field

MODEL_ID = os.environ.get("AVATAR_MODEL", "stabilityai/sdxl-turbo")
API_KEY = os.environ.get("AVATAR_API_KEY")
PORT = int(os.environ.get("AVATAR_PORT", "8188"))

#: SDXL Turbo's native size. Going higher does not help — it was distilled at
#: this resolution and drifts badly above it.
SIZE = 512

app = FastAPI(title="avatar-service")
_pipe = None
_checker = None


class GenerateRequest(BaseModel):
    #: Assembled server-side from trait keys. This service never sees player
    #: text, and is not the thing enforcing that — the platform is.
    prompt: str = Field(max_length=2000)
    seed: int = 0
    #: Turbo is distilled to work in very few steps. More is slower, not better.
    steps: int = Field(default=4, ge=1, le=12)
    model: str = ""


def _gpu() -> dict:
    """What the GPU situation actually is, not just whether CUDA imported.

    ``torch.cuda.is_available()`` returns **True on a card this build has no
    kernels for** — an RTX 5090 is sm_120 and a cu124 wheel stops at sm_90. You
    find out later, mid-generation, as ``CUDA error: no kernel image is
    available for execution on the device``. So compare the device's compute
    capability against the arch list the wheel was built with, and say so.
    """
    if not torch.cuda.is_available():
        return {"cuda": False, "usable": False, "why": "no CUDA device visible"}

    major, minor = torch.cuda.get_device_capability(0)
    arch = f"sm_{major}{minor}"
    supported = torch.cuda.get_arch_list()
    usable = arch in supported
    info = {
        "cuda": True,
        "usable": usable,
        "device": torch.cuda.get_device_name(0),
        "capability": arch,
        "torch": torch.__version__,
        "arch_list": supported,
    }
    if not usable:
        info["why"] = (
            f"this torch build has no kernels for {arch} "
            f"(it supports {', '.join(supported)}). Install a CUDA build that "
            "matches your card — see README.md."
        )
    return info


def _load():
    """Loaded once, on the first request rather than at import.

    Keeps `--reload` and a quick `GET /health` from paying for a model load.
    """
    global _pipe, _checker
    if _pipe is not None:
        return _pipe, _checker

    from diffusers import AutoPipelineForText2Image
    from transformers import CLIPImageProcessor

    gpu = _gpu()
    if gpu["cuda"] and not gpu["usable"]:
        # Refuse rather than falling back silently: a CPU fallback here is
        # minutes per image, which looks like a hang rather than a downgrade.
        raise RuntimeError(gpu["why"])

    device = "cuda" if gpu["usable"] else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32
    if device == "cpu":
        print("WARNING: no usable GPU — generating on CPU. This will be slow.")

    _pipe = AutoPipelineForText2Image.from_pretrained(
        MODEL_ID, torch_dtype=dtype, variant="fp16" if device == "cuda" else None
    ).to(device)

    try:
        from diffusers.pipelines.stable_diffusion.safety_checker import (
            StableDiffusionSafetyChecker,
        )

        _checker = (
            StableDiffusionSafetyChecker.from_pretrained(
                "CompVis/stable-diffusion-safety-checker", torch_dtype=dtype
            ).to(device),
            CLIPImageProcessor.from_pretrained("openai/clip-vit-base-patch32"),
        )
    except Exception as exc:  # noqa: BLE001
        # Load it or say so. Running without it is a decision the operator makes
        # knowingly, not something that happens quietly.
        print(f"WARNING: safety checker unavailable ({exc}). Generation is unfiltered.")
        _checker = None

    return _pipe, _checker


@app.get("/health")
def health() -> dict:
    gpu = _gpu()
    return {"ok": True, "model": MODEL_ID, "gpu": gpu}


@app.post("/generate")
def generate(payload: GenerateRequest) -> Response:
    pipe, checker = _load()

    generator = torch.Generator(device=pipe.device).manual_seed(payload.seed or 0)
    image = pipe(
        prompt=payload.prompt,
        num_inference_steps=payload.steps,
        # **Turbo ignores guidance**, which is why the platform cannot use a
        # negative prompt and why its trait vocabulary has to be the filter.
        # Setting it to anything else degrades the image.
        guidance_scale=0.0,
        height=SIZE,
        width=SIZE,
        generator=generator,
    ).images[0]

    if checker is not None:
        model, processor = checker
        inputs = processor(images=image, return_tensors="pt").to(model.device)
        # **numpy, not PIL.** The checker blacks out anything it flags, in
        # place, with `images[idx] = np.zeros(images[idx].shape)` — so a PIL
        # Image raises AttributeError, and only on the flagged path, which is
        # the worst place to find out. We want the verdict, not the blacked
        # array, so what goes in is a throwaway copy.
        _, flagged = model(
            images=[np.array(image)], clip_input=inputs.pixel_values.to(model.dtype)
        )
        if any(flagged):
            # Logged because otherwise its false-positive rate is invisible.
            # This classifier is known to be trigger-happy on stylised art, and
            # if it starts refusing ordinary dwarves you want to see that in the
            # log rather than infer it from players complaining.
            print(f"refused seed={payload.seed}: {payload.prompt[:120]}")
            # 422 rather than 500: the platform reads this as "refused", leaves
            # its circuit breaker shut, and tells the player to try other
            # choices rather than reporting the host as broken. It also has
            # three other seeds in flight, so one refusal is not a dead job.
            return Response(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return Response(content=buffer.getvalue(), media_type="image/png")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
