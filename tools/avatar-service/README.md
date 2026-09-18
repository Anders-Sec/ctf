# Avatar generation service

A small SDXL Turbo service for spec 074. It runs on **your GPU box**, beside the
LM Studio host — not in the cluster, and not from the platform's deployment.

The platform treats it exactly the way it treats the model host: optional, and
expected to be unreachable sometimes. When it is off, portrait generation is not
offered and everything spec 073 built — crests, accessories, the editor — keeps
working with no GPU at all.

## What it needs

- A GPU with roughly **8GB of VRAM** for SDXL Turbo at fp16. It will run on CPU
  and you will not enjoy it.
- Python 3.11 or newer.

```
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install diffusers transformers accelerate safetensors fastapi uvicorn pillow
python service.py
```

The first request downloads the weights (~7GB) and takes a few minutes. Every
request after that is a second or two.

## Configuration

| Variable | Default | |
| --- | --- | --- |
| `AVATAR_MODEL` | `stabilityai/sdxl-turbo` | Any text-to-image pipeline `diffusers` can load |
| `AVATAR_PORT` | `8188` | |
| `AVATAR_API_KEY` | unset | Sent by the platform as a bearer token |

Then point the platform at it, **in configuration and never in the repo**:

```
IMAGE_BASE_URL=http://<your-host>:8188
IMAGE_API_KEY=<if you set one>
IMAGE_ENABLED=true
```

## Swapping the model

The contract is prompt in, PNG out, so anything `diffusers` can load will do.
**Flux Schnell** (`black-forest-labs/FLUX.1-schnell`) is noticeably better at
coherence and hands, also works in about four steps, and wants roughly 12GB of
VRAM or more — a straight swap on a bigger card:

```
AVATAR_MODEL=black-forest-labs/FLUX.1-schnell python service.py
```

## Two things worth knowing

**Turbo ignores negative prompts.** It runs at `guidance_scale=0.0` by design,
so the usual "add a negative prompt" control does nothing. This is why the
platform never lets a player type a prompt at all — the authored trait
vocabulary is the filter, and this service's NSFW classifier is the backstop
behind it.

**The classifier is the only thing here the platform cannot do**, because this
is where the GPU is. If it fails to load, the service prints a warning and
generates unfiltered rather than silently dropping the check — running without
it should be a decision you made, not one that happened.

## Checking it

```
curl http://localhost:8188/health
curl -X POST http://localhost:8188/generate \
  -H 'content-type: application/json' \
  -d '{"prompt":"a stout dwarf, oil painting","seed":1,"steps":4}' \
  --output test.png
```

A refusal from the classifier comes back as **422** with no body. The platform
reads that as "try different choices" rather than "the host is broken", and
leaves its circuit breaker shut.
