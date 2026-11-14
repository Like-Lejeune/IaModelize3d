"""Vérifie le fournisseur d'IA configuré avant de lancer le vrai serveur : quatre petits appels, comme ceux du concepteur.

    .venv/bin/python scripts/check_llm.py            (Windows : .\\.venv\\Scripts\\python.exe scripts\\check_llm.py)

Il lit la même configuration que le serveur (.env à la racine du dépôt ou un dossier au-dessus, variables FW_*), puis
essaie : 1. une réponse en texte, 2. une réponse JSON selon un schéma (accueil des demandes, critique),
3. un appel d'outil (le concepteur dessine avec des outils), 4. la lecture d'une image (photos de pièces), et la
réflexion au niveau le plus profond que le concepteur demande. Coût : une fraction de centime.
"""
from __future__ import annotations

import asyncio
import base64
import struct
import sys
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from iamodelize3d.config import settings  # noqa: E402
from iamodelize3d.llm.client import CostMeter, MetaClient, provider_effort  # noqa: E402


def red_square_png() -> str:
    """A 32 × 32 red PNG, written by hand so the check needs no image library."""
    w = h = 32
    raw = b"".join(b"\x00" + b"\xd0\x20\x20" * w for _ in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(png).decode()


def tool_calls(resp) -> list:
    return [o for o in (resp.output or []) if getattr(o, "type", "") == "function_call"]


async def main() -> int:
    s = settings()
    p = s.provider
    print(f"Fournisseur : {p['name']}  ({s.api_base_url})")
    print(f"Clé : {'présente' if s.api_key else 'ABSENTE'}")
    print(f"Modèles : concepteur {s.model_designer}, concepteur fort {s.model_designer_hard}, rapide {s.model_fast}, gratuit {s.model_free}")
    top = provider_effort(s, "max")
    print("Réflexion : " + ("désactivée (FW_LLM_REASONING=0)" if not s.llm_reasoning else f"jusqu'à « {top} »"))
    print(f"Mesure sur photo (SAM), voix, images : {'oui' if s.can('sam') else 'non (Meta uniquement)'}\n")
    if not s.api_key:
        print("Ajoutez la clé dans .env : FW_LLM_API_KEY=... (ou META_API_KEY=... pour Meta).")
        return 1

    c = MetaClient()
    meter = CostMeter(budget_usd=0.5)
    model = s.model_fast
    failures = 0

    async def step(name: str, run) -> None:
        nonlocal failures
        t0 = time.monotonic()
        try:
            detail = await run()
            print(f"  OK     {name} ({time.monotonic() - t0:.1f} s){f' : {detail}' if detail else ''}")
        except Exception as e:  # noqa: BLE001 - the check reports every failure and goes on
            failures += 1
            print(f"  ÉCHEC  {name} : {type(e).__name__}: {str(e)[:400]}")

    async def text():
        r = await c.respond(meter, model=model, input=[{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "Réponds seulement : bonjour"}]}], effort="low", max_output_tokens=2000, purpose="check")
        return repr((r.output_text or "").strip()[:60])

    async def structured():
        out = await c.json(meter, model=model, system="Tu lis une demande de pièce et tu la résumes.",
                           content=[{"type": "input_text", "text": "La molette de mon ventilateur Binatone est cassée, axe de 6 mm."}],
                           schema={"type": "object", "additionalProperties": False, "required": ["piece", "diametre_mm"],
                                   "properties": {"piece": {"type": "string"}, "diametre_mm": {"type": "number"}}},
                           name="check", purpose="check")
        if not out:
            raise RuntimeError("aucune réponse JSON exploitable")
        return str(out)

    async def tools():
        tool = {"type": "function", "name": "set_box", "description": "Dessine une boîte aux dimensions données (mm).",
                "parameters": {"type": "object", "properties": {"width": {"type": "number"}, "height": {"type": "number"}},
                               "required": ["width", "height"]}}
        r = await c.respond(meter, model=s.model_designer, input=[{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "Dessine une boîte de 120 mm de large et 50 mm de haut avec l'outil."}]}],
            tools=[tool], effort="low", max_output_tokens=4000, purpose="check")
        calls = tool_calls(r)
        if not calls:
            raise RuntimeError(f"le modèle n'a pas appelé l'outil (réponse : {(r.output_text or '')[:120]!r})")
        return f"{calls[0].name}({calls[0].arguments})"

    async def vision():
        r = await c.respond(meter, model=model, input=[{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "De quelle couleur est cette image ? Un seul mot."},
            {"type": "input_image", "image_url": red_square_png()}]}], effort="low", max_output_tokens=2000, purpose="check")
        return repr((r.output_text or "").strip()[:40])

    async def deep():
        r = await c.respond(meter, model=s.model_designer_hard, input=[{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": "Combien font 17 × 23 ? Le nombre seulement."}]}], effort="max", max_output_tokens=4000,
            purpose="check")
        return f"{(r.output_text or '').strip()[:20]!r}, effort envoyé : {provider_effort(s, 'max') or 'aucun'}"

    print(f"Essais sur {model} (et {s.model_designer} pour l'outil, {s.model_designer_hard} pour la réflexion profonde) :")
    await step("1. texte", text)
    await step("2. JSON selon un schéma", structured)
    await step("3. appel d'outil", tools)
    await step("4. lecture d'une image", vision)
    await step("5. réflexion profonde", deep)
    print(f"\nCoût de la vérification : {meter.usd:.4f} USD" if meter.usd else
          "\nCoût non compté : ce modèle n'est pas dans la table des prix (FW_LLM_PRICE_IN_PER_M / _OUT_PER_M).")
    if failures:
        print(f"{failures} essai(s) en échec : le studio ne marchera pas correctement avec ce réglage.")
        return 1
    print("Tout fonctionne : lancez le serveur avec la vraie IA.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
