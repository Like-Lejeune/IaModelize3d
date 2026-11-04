"""How the pack modules (elec_tools, pcb_tools, contract C9) plug into the agent hub: the tool list of every pack is well
formed, stable (prompt caching) and dispatchable; the classifier knows the new packs; their texts and examples go into
the pack's own block; the PCB pack gets its own output budget; and a module that fails to import takes only its pack away."""
import json
import os
import subprocess
import sys

import pytest

from formwright.agent import device_inspect, device_tools, elec_tools, examples, loop, pcb_tools, prompts, tools
from formwright.config import REPO_DIR
from formwright.llm.english import is_english

HUB = {t["name"] for t in (tools.WRITE, tools.EDIT, tools.SET_PARAMS, tools.INSPECT, tools.LOOK, tools.DIMENSIONS, tools.ASK, tools.FINISH,
                            tools.MEASURE, tools.FIT, tools.REMEMBER, tools.PROBE, tools.CONCEPTS, tools.TERRAIN, tools.COMPARE_PRINT,
                            tools.MESH_WRITE, tools.MESH_EDIT)}
COMBOS = [(photos, prints, engine) for photos in (False, True) for prints in (False, True) for engine in ("cad", "mesh")]


@pytest.mark.parametrize("pack", prompts.PACK_NAMES)
def test_every_pack_gets_a_stable_well_formed_tool_list(pack):
    for photos, prints, engine in COMBOS:
        ts = tools.tools_for(pack, photos=photos, prints=prints, engine=engine)
        names = [t["name"] for t in ts]
        assert len(names) == len(set(names)) and names[-1] == "finish"
        assert names == [t["name"] for t in tools.tools_for(pack, photos=photos, prints=prints, engine=engine)]
        for t in ts:
            assert t["type"] == "function" and t["parameters"]["type"] == "object" and set(t["parameters"]["required"]) <= set(t["parameters"]["properties"])
            assert is_english(json.dumps(t)), t["name"]
        # run_tool knows every one of them
        assert set(names) <= HUB | elec_tools.NAMES | pcb_tools.NAMES | device_tools.NAMES | device_inspect.NAMES, set(names) - HUB


def test_the_electronics_packs_and_the_others_keep_their_lists():
    names = lambda pack, **kw: [t["name"] for t in tools.tools_for(pack, **{"photos": False, "prints": False, **kw})]  # noqa: E731
    assert names("household") == ["write_program", "edit_program", "set_params", "inspect_model", "look", "dimensions", "ask_user",
                                   "remember_interface", "propose_probe", "finish"]
    assert names("enclosure") == ["write_program", "edit_program", "set_params", "inspect_model", "look", "dimensions", "ask_user",
                                  "use_board", "check_enclosure", "remember_interface", "propose_probe", "finish"]
    assert names("enclosure", photos=True) == ["write_program", "edit_program", "set_params", "inspect_model", "look", "dimensions", "ask_user",
                                               "measure", "fit_to_photo", "use_board", "scan_board", "check_enclosure", "remember_interface",
                                               "propose_probe", "finish"]
    pcb = ["write_circuit", "check_pcb", "export_fab", "make_enclosure", "look", "dimensions", "ask_user", "finish"]
    assert names("pcb") == pcb and names("pcb", photos=True, prints=True) == pcb
    # the PCB pack's look knows the board's own views
    look = next(t for t in tools.tools_for("pcb", photos=False, prints=False) if t["name"] == "look")
    assert look is pcb_tools.LOOK and {"pcb", "schematic"} <= set(look["parameters"]["properties"]["what"]["enum"])


def test_the_classifier_knows_the_new_packs():
    enum = loop.CLASSIFY_SCHEMA["properties"]["pack"]["enum"]
    assert enum == prompts.PACK_NAMES and {"enclosure", "pcb"} <= set(enum)
    assert "\nenclosure (a case, box or housing for an electronics board" in prompts.CLASSIFY
    assert "\npcb (design a printed circuit board itself" in prompts.CLASSIFY and prompts.CLASSIFY.count("{") == 0
    assert prompts.PACKS["enclosure"].strip() == elec_tools.PACK_TEXT and prompts.PACKS["pcb"].strip().startswith("# Pack: printed circuit boards")
    for text in (*prompts.PACKS.values(), prompts.CLASSIFY):
        assert is_english(text)


def test_pack_text_and_example_go_into_the_pack_block():
    shared = prompts.SYSTEM + "\n\n" + examples.EXAMPLES_TEXT + "\n\n"
    for pack in prompts.PACK_NAMES:
        text = loop.instructions_for(pack, "cad")
        assert text.startswith(shared + prompts.PACKS[pack])  # the cached prefix is the same for every pack
        if pack in examples.PACK_EXAMPLES:
            assert text.endswith(examples.PACK_EXAMPLES[pack])
    assert loop.instructions_for("household", "cad") == shared + prompts.PACKS["household"]
    assert loop.instructions_for("collect", "mesh").endswith(prompts.MESH_ENGINE)
    # the collect pack asks for the size on the longest side and a named plinth (snap's request)
    assert "fit: {longest: '$size'}" in prompts.PACKS["collect"] and "plinth 3-4 mm" in prompts.PACKS["collect"]


def test_the_pcb_pack_gets_its_own_output_budget():
    assert loop.llm_options("pcb", "medium") == ("low", 24000)
    assert loop.llm_options("pcb", "max") == ("low", 24000)
    assert loop.llm_options("household", "high") == ("high", 20000)
    assert loop.llm_options("household", "medium") == ("medium", 12000)
    assert loop.llm_options("enclosure", "xhigh") == ("xhigh", 28000)


def _python(code: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "META_API_KEY": "", "META_KEY": "", "FW_META_API_KEY": "", "FW_OPEN_BASE_URL": "", "FW_TELEGRAM_TOKEN": ""}
    return subprocess.run([sys.executable, "-c", code], cwd=str(REPO_DIR / "server"), env=env, capture_output=True, text=True, timeout=120)


def test_a_missing_pack_module_takes_only_its_pack_away():
    r = _python(
        "import logging, sys\n"
        "logging.basicConfig(level=logging.ERROR, stream=sys.stdout, format='%(levelname)s %(message)s')\n"
        "sys.modules['formwright.agent.pcb_tools'] = None\n"
        "import formwright.app\n"
        "from formwright.agent import examples, loop, prompts, tools\n"
        "print('PACKS', sorted(prompts.PACKS))\n"
        "print('PCB', [t['name'] for t in tools.tools_for('pcb', photos=False, prints=False)])\n"
        "print('EXAMPLES', sorted(examples.PACK_EXAMPLES))\n")
    assert r.returncode == 0, r.stderr[-2000:]
    assert "ERROR agent tools: pcb_tools did not import, pack 'pcb' is off" in r.stdout
    assert "PACKS ['adapter', 'collect', 'copy', 'enclosure', 'forms', 'household', 'landmark', 'mechanisms', 'stylize', 'terrain']" in r.stdout
    assert "PCB ['write_program'," in r.stdout and "EXAMPLES ['enclosure']" in r.stdout
    r = _python(
        "import sys\n"
        "sys.modules['formwright.agent.elec_tools'] = None\n"
        "from formwright.agent import loop, prompts, tools\n"
        "print('PACKS', sorted(prompts.PACKS))\n"
        "print('ENC', [t['name'] for t in tools.tools_for('enclosure', photos=True, prints=False)])\n")
    assert r.returncode == 0, r.stderr[-2000:]
    assert "'enclosure'" not in r.stdout.split("PACKS", 1)[1].splitlines()[0] and "'pcb'" in r.stdout
    assert "scan_board" not in r.stdout
