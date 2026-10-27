# Formwright

An agent that designs printable 3D models for your real world — from a photo of a broken part next
to a sheet of paper, a caliper reading, a sketch, a voice note or just an idea — and checks them
against reality before you print.

It does not generate meshes. Muse models write small parametric programs; a geometry kernel builds
them; measurements come from computer vision, standards tables and web search, never from guessing;
every version passes a slicer-like printability check and an independent critic.

## What it does

- **Measures the real world.** SAM 3.1 segments the part and any known reference in the photo (A4/Letter
  sheet, bank card, coin, battery, LEGO brick), the reference gives scale and camera pose, outlines come
  out in millimetres with an uncertainty per dimension. Caliper photos are read directly.
- **Designs for the place, not only the copy.** Exact interfaces (holes, threads, shelf edges, sockets,
  hoses) from measurements, standards and official specs; free form everywhere else.
- **Programs, not meshes.** Every model is a short JavaScript program with parameters, sliders and
  draggable handles. It runs in the browser for live editing and in a sandboxed server worker for checks
  and export.
- **Checks like a slicer.** A layer-by-layer mini-slicer reports floating islands, long bridges,
  overhangs, features thinner than an extrusion line, vase-mode problems — with the exact height and
  position, so the agent can fix them. OrcaSlicer CLI gives the final time and weight.
- **Verifies against reality.** When copying from a photo, every build comes back next to the object on the
  photo, seen from the same angle (or drawn over it with the photo's own camera), with a silhouette match;
  an optimizer can fit outline parameters to the photo silhouette; uncertain fits become a 5-minute
  probe print; a printed calibration coupon gives each printer a fingerprint that later designs
  compensate for.
- **Justified print profiles.** Starts from the printer's stock Orca profile and changes a setting only
  with evidence from the geometry or the user's goal; every change carries its reason. Modifier volumes
  reinforce screw areas locally.
- **Creative packs.** Generative vases and lamps, gyroid lattices, real terrain from open elevation data,
  landmarks, stylized figures, print-in-place mechanisms, multi-colour parts; concept images, breeding
  variants, and editing by drawing on the render.
- **Memory that does not bloat.** Measured interfaces of your world, lessons from repeated fixes and
  tested skills enter memory only with evidence, leave it when unused, and only relevant items reach the
  prompt.
- **Readable work log.** Every job shows its stage (understand → measure → design → check → review → ready),
  each step as a sentence in your language, the model's reasoning summaries, and a result card with key
  dimensions, their sources, printability and cost. Any public project can be replayed step by step without
  spending tokens.
- **Order a print.** Download STL/3MF (with print settings), or order printing and delivery in Kazakhstan
  through Axo. A Telegram bot accepts photos and voice notes too.

## How it works

```
 browser (SvelteKit, three.js)                 server (FastAPI)
 ┌───────────────────────────────┐  SSE  ┌──────────────────────────────────────────┐
 │ studio: chat, 3D, sliders,    │◄──────│ agent loop (Muse Spark / Wonder, tools)   │
 │ handles, photo-AR, WebXR      │       │  ├ vision: SAM 3.1, calibration, caliper  │
 │ geometry worker (same code) ──┼──┐    │  ├ knowledge: standards, web search facts │
 └───────────────────────────────┘  │    │  ├ critic: renders + photos, no code      │
                                    │    │  ├ memory: interfaces, lessons, skills    │
     packages/geom (TypeScript)     │    │  └ printing: Orca CLI, profiles, probes   │
     manifold kernel, std library,  ├────┤ sandboxed Node workers (vm + permissions)  │
     checks, renderer, 3MF export ──┘    └──────────────────────────────────────────┘
```

## Meta models

| Model | Role |
|---|---|
| Muse Spark 1.3 | designer and tool loop, intake, critic, search grounding for dimensions, print-profile review |
| Muse Wonder | "hard mode" designer for complex parts |
| SAM 3.1 | measurement: reference objects, parts, holes, faces (privacy blur), video tracking |
| Muse Spark 1.2 | video + audio understanding ("show and tell" clips) |
| Muse Voice Transcribe | voice notes with 3D-printing keyword biasing |
| Muse Image | concept images, visual edits from strokes on a render |
| Muse Glimmer (open weights) | optional independent critic served on your own GPU (`infra/modal_glimmer.py`) |
| MapAnything (open weights) | optional multi-view metric reconstruction (`infra/modal_mapanything.py`) |

## Run locally

Requirements: Node 24, Python 3.12+, OrcaSlicer (for slicing), ffmpeg (for audio/video), a Meta Model API key.

```bash
npm install
npm run build -w web
cd server
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # .venv/bin/pip on Linux/macOS
echo META_API_KEY=... > ../.env
.venv/Scripts/python -m uvicorn formwright.app:app --port 8000
```

Open http://localhost:8000. For UI development run `npm run dev -w web` (port 5173, proxies the API).

Container: `docker build --build-arg ORCA_APPIMAGE_URL=<OrcaSlicer Linux AppImage> -t formwright .`

For cheap development runs point the models at the Contributor tier (content may be used to train Meta
models): `FW_MODEL_DESIGNER=muse-spark-1.3-contributor FW_MODEL_FAST=muse-spark-1.3-contributor
FW_MODEL_CRITIC=muse-spark-1.3-contributor` — a full design job then costs well under a cent.

Useful settings (environment, prefix `FW_`): `FW_ORCA_BIN`, `FW_ORCA_PROFILES`, `FW_DAILY_BUDGET_USD`,
`FW_TELEGRAM_TOKEN`, `FW_AXO_API_URL` / `FW_AXO_API_KEY`, `FW_OPEN_BASE_URL` / `FW_OPEN_MODEL` /
`FW_MODEL_CRITIC` (open-weights critic).

## Tests

```bash
npm test                                   # geometry kernel, checks, sketch solver
cd server && .venv/Scripts/python -m pytest  # vision, printing, sandbox, pipeline
```

## Built during the hackathon

Everything in this repository was written during the Meta Global AI Developer Hackathon
(27 Oct – 4 Nov 2026). Axo (axo.kz), an existing 3D-printing business in Kazakhstan, is used only as an
external print-and-delivery service through its API; none of its code is here.

## License

[PolyForm Noncommercial 1.0.0](LICENSE). Models you create with Formwright are yours.
