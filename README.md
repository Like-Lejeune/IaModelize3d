# Formwright

An agent that designs printable 3D models for the real world from a photo, a caliper reading, a sketch,
a voice note or an idea, and checks them against reality before you print.

Models write short parametric programs, a geometry kernel builds them. Dimensions come from computer
vision, standards tables and official specs, not from guessing. Every version passes a slicer-like
printability check and an independent critic.

## Features

- **Measurement from photos.** SAM 3.1 finds the part and a known reference (A4/Letter sheet, bank card,
  coin, battery, LEGO brick); outlines and holes come out in millimetres with an uncertainty. Caliper
  displays are read directly.
- **Parametric programs.** Each model is a JavaScript program with sliders and draggable handles. The same
  code runs in the browser for live editing and in a sandboxed server worker for checks and export.
- **Exact and free-form geometry.** CSG with standard holes, threads, gears and hinges; signed distance
  fields with smooth blends, lofts, sweeps, subdivision smoothing, 3D rounding, grooves and embossing that
  follow curved surfaces, and mesh sculpting. Uploaded STL/OBJ files can be edited too.
- **Printability checks.** A layer-by-layer mini-slicer reports islands, bridges, overhangs and thin
  features with exact positions. OrcaSlicer gives time and weight.
- **Verification against the photo.** Builds are rendered next to the photographed object from the same
  angle with a silhouette match; an optimizer fits parameters to the silhouette; uncertain fits become a
  short probe print; a calibration coupon gives each printer a correction profile.
- **Print profiles with reasons.** Settings change from the stock Orca profile only with evidence, and
  modifier volumes reinforce screw areas.
- **Creative packs.** Vases and lamps, gyroid lattices, terrain from open elevation data, landmarks,
  figures, print-in-place mechanisms, multi-colour parts, concept images.
- **Memory.** Measured interfaces, lessons from repeated fixes and tested modules are kept only with
  evidence and recalled only when relevant.
- **Work log.** Each job shows its stages, steps in the user's language and a result card with dimensions,
  their sources, printability and cost. Public projects can be replayed.
- **Output.** STL/3MF with print settings, print-and-delivery orders in Kazakhstan through Axo, and a
  Telegram bot for photos and voice notes.

## Architecture

```
 browser (SvelteKit, three.js)                 server (FastAPI)
 ┌───────────────────────────────┐  SSE  ┌──────────────────────────────────────────┐
 │ chat, 3D view, sliders,       │◄──────│ agent loop (Muse Spark / Wonder, tools)   │
 │ handles, photo AR, WebXR      │       │  ├ vision: SAM 3.1, calibration, caliper  │
 │ geometry worker (same code) ──┼──┐    │  ├ knowledge: standards, web search       │
 └───────────────────────────────┘  │    │  ├ critic: renders + photos, no code      │
                                    │    │  ├ memory: interfaces, lessons, skills    │
     packages/geom (TypeScript)     │    │  └ printing: Orca CLI, profiles, probes   │
     manifold kernel, libraries,    ├────┤ sandboxed Node workers (vm + permissions)  │
     checks, renderer, 3MF export ──┘    └──────────────────────────────────────────┘
```

## Models

| Model | Role |
|---|---|
| Muse Spark 1.3 | designer, intake, critic, dimension search, print-profile review |
| Muse Wonder | designer for complex parts |
| SAM 3.1 | segmentation for measurement, privacy blur, video tracking |
| Muse Spark 1.2 | video and audio understanding |
| Muse Voice Transcribe | voice notes |
| Muse Image | concept images and visual edits |
| Muse Glimmer (open weights, optional) | independent critic on your own GPU (`infra/modal_glimmer.py`) |
| MapAnything (open weights, optional) | multi-view metric reconstruction (`infra/modal_mapanything.py`) |

## Running locally

Requirements: Node 24, Python 3.12+, a Meta Model API key; OrcaSlicer for slicing and ffmpeg for audio
and video are optional.

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

Settings are environment variables with the `FW_` prefix: `FW_MODEL_DESIGNER`, `FW_MODEL_FAST`,
`FW_MODEL_CRITIC`, `FW_ORCA_BIN`, `FW_ORCA_PROFILES`, `FW_DAILY_BUDGET_USD`, `FW_TELEGRAM_TOKEN`,
`FW_AXO_API_URL`, `FW_AXO_API_KEY`, `FW_OPEN_BASE_URL`, `FW_OPEN_MODEL`.

## Tests

```bash
npm test                                     # geometry kernel, checks, sketch solver
cd server && .venv/Scripts/python -m pytest  # vision, printing, sandbox, pipeline
```

## License

[PolyForm Noncommercial 1.0.0](LICENSE). Models you create with Formwright are yours.

Written during the Meta Global AI Developer Hackathon (27 Oct – 4 Nov 2026). Axo (axo.kz) is used only as
an external print-and-delivery API; none of its code is here.
