"""The virtual board: run a device's firmware on its own circuit before anyone orders it.

Static checks read how a design is written; three devices of 2026-11-04 passed all of them and still did not work (a leak alarm
that re-armed itself at once, an 8-day battery called months, ...). So this runs it, with one mechanism in place of a rule per mistake:
  - firmware_sim/runtime.cpp compiled with the sketch to WebAssembly (zig c++): no file, network or clock of the server reaches
    it, fuel bounds it, and a call with no body here stops the run as 'not modelled' instead of passing.
  - Circuit solves the graph as a small DC network (resistors, LEDs and diodes, BJTs and MOSFETs as switches, parts as loads): what
    an input pin sees, what a load draws, which rail it comes from. Nothing in it is about a device.
  - scenarios are made from the graph alone: every input pressed in every condition, a wet probe that stays wet, a day left alone.
  - invariants judge the runs: no hang, sleep that really sleeps, every input changes something, every output can turn on, nothing
    read from a floating pin, what the battery really gives.
  - a requirement's own test (doc.requirements[].test) is played as written, for what only a sequence shows. The designer writes it
    and the run judges it; a test that also passes with its steps removed proves nothing and is reported as such.

simulate(doc, parts, files, lang) -> {ran, ok, why?, findings: [{code, severity, ref, msg, hint?, trace?}], effects, power, coverage,
scenarios, ms}; never raises. ran False says nothing about the device (MicroPython, a Pico, no compiler here): the caller says 'not
simulated', never 'passed'.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from bisect import bisect_right
from pathlib import Path
from typing import Any

import numpy as np

from . import device, device_rules as dr, firmware_check as fc

log = logging.getLogger(__name__)

HERE = Path(__file__).parent
RUNTIME = HERE / "firmware_sim" / "runtime.cpp"
STUBS = HERE / "firmware_stubs"
COMPILE_S = 45.0
BOARDS = {"113991054", "113991114"}       # the ESP32 family: runtime.cpp models its sleep and its core
ADC_FULL_MV = {"ESP32-C3": 2500, "ESP32-S3": 3100}   # what 12 bits span at the default attenuation
# what the module itself draws from a cell, mA: running with the radio off, light sleep, deep sleep (Seeed's XIAO figures)
MCU_MA = {"ESP32-C3": (25.0, 0.35, 0.044), "ESP32-S3": (40.0, 2.0, 0.014)}
EXIT_END, EXIT_SLEPT, EXIT_RESTART = 0, 10, 11
RAIL_R, GPIO_R, GND_R = 0.05, 30.0, 0.01
GMIN = 1e-9
FLOATING_OHM = 3e7
GPIO_ABS_MA = 40.0
SLEEP_FLOOR_MA = 1.0      # asleep on a cell, a part left on above this is the design's battery life
BOOT_LIMIT = 1500
BOOT_LOOP_S = 3.0      # one boot this often, with nothing changing, is a loop
RADIO_MA = 65.0        # the radio on, on top of running
SCENARIO_FUEL = 1_000_000_000
IDLE_FUEL = 3_000_000_000
WALL_S = 40.0
MAX_RUNS = 36
PRESS_AT_S, SECOND_AT_S, HORIZON_S = 45.0, 100.0, 170.0
STUCK_S, LONG_S, IDLE_S = 900.0, 1800.0, 6 * 3600.0
ASM = re.compile(r"\b(asm|__asm|__asm__|incbin)\b")
LOAD_MA = {"buzzer": 30.0, "buzzer_active": 30.0, "buzzer_passive": 5.0, "speaker": 100.0, "motor": 100.0, "relay": 70.0}
OUTPUT_KINDS = ("led", "buzzer", "buzzer_active", "buzzer_passive", "speaker", "motor", "relay", "rgb_led", "display", "servo")
PIR = re.compile(r"\bPIR\b|AM312|SR501|SR602|Human Body", re.I)
I2C_LIGHT = re.compile(r"BH1750|VEML|TSL25|OPT3001|Ambient Light", re.I)
I2C_CLIMATE = re.compile(r"BME280|BMP280|SHT[34]|AHT[12]|HDC10", re.I)


# ------------------------------------------------------------------ the circuit
class Circuit:
    """The graph as a DC network. env: {stimulus id: value}; states: {gpio: 0 hi-z, 1 low, 2 high}; display: ids that are on."""

    def __init__(self, doc: dict[str, Any], parts: dict[str, dict[str, Any]]) -> None:
        self.doc = doc
        self.g = g = dr._G(doc, parts)
        self.module = g.modules[0] if g.modules else None
        self.mcu = str((device.MODULES.get(g.nodes[self.module].get("module")) or {}).get("mcu")) if self.module else ""
        gpio = g.mod(self.module)[0] if self.module else {}
        self.gpio_net = {n: g.net(self.module, lb) for lb, n in gpio.items() if g.net(self.module, lb) is not None}
        self.gpio_label = {n: lb for lb, n in gpio.items()}
        self.n = len(g.nets)
        self.on_battery, self.capacity_mah, self.battery = False, 0.0, None
        self.res: list[tuple[int, int, float, str]] = []
        self.diodes: list[tuple[int, int, float, str]] = []
        self.bjts: list[tuple[str, int, int, int, str]] = []
        self.mos: list[tuple[str, int, int, int, str]] = []
        self.buttons: dict[str, tuple[int, int]] = {}
        self.contacts: dict[str, tuple[int, int, float]] = {}
        self.ldr: dict[str, tuple[int, int]] = {}
        self.ntc: dict[str, tuple[int, int]] = {}
        self.sources: dict[str, dict[str, Any]] = {}
        self.loads: dict[str, dict[str, Any]] = {}
        self.outputs: dict[str, str] = {}
        self.displays: dict[int, str] = {}
        self.i2c: set[int] = set()
        self.i2c_any = False
        self.stimuli: list[dict[str, Any]] = []
        self.unmodelled: dict[int, str] = {}
        self.buses: set[str] = set()
        self.keeps_image = False
        self._cache: dict[Any, Any] = {}
        for nid, node in g.nodes.items():
            if nid != self.module:
                self._add(nid, node)
        self.rails = [(i, v) for i in range(self.n) for v in [g.volt(i)] if v is not None and not g.gnd(i)]
        self.grounds = [i for i in range(self.n) if g.gnd(i)]
        for gp, net in self.gpio_net.items():
            if not self._modelled(net) and not g.i2c_net(net):
                who = next((a for a, _ in g.on[net] if a != self.module), None)
                if who:
                    self.unmodelled[gp] = who

    def _modelled(self, net: int) -> bool:
        known = {"resistor", "button", "led", "diode", "capacitor"}
        for nid, _ in self.g.on[net]:
            if nid == self.module:
                continue
            if self.g.nodes[nid].get("kind") in known or nid in self.outputs or nid in self.sources \
                    or nid in self.contacts or nid in self.ldr or nid in self.ntc or nid in self.buttons or nid in self.buses:
                return True
            if self.g.kind[nid] in dr.SWITCHES or self.g.addressable(nid):
                return True
        return False

    def _two(self, nid: str) -> tuple[int, int] | None:
        nets = [n for _, n in self.g.wired(nid)]
        uniq = list(dict.fromkeys(nets))
        return (uniq[0], uniq[1]) if len(uniq) >= 2 else None

    def _load(self, nid: str, ma: float, **extra: Any) -> None:
        """A part with a supply: it draws its current while its supply pin is up, wherever that pin is wired."""
        g, sup, gnd = self.g, None, None
        for p, net in g.wired(nid):
            if g.gnd(net):
                gnd = net
            elif dr.SUPPLY_PIN.match(p["label"]) or dr.SUPPLY_PIN.match(p["name"] or "") or (g.rail(net) and sup is None):
                sup = net
        if sup is not None and gnd is not None and ma > 0:
            self.loads[nid] = {"a": sup, "b": gnd, "ma": ma, **extra}

    def _add(self, nid: str, node: dict[str, Any]) -> None:
        g, k, kind = self.g, node.get("kind"), g_kind(self.g, nid)
        if k == "resistor":
            a, b = g.net(nid, "1"), g.net(nid, "2")
            if a is not None and b is not None:
                self.res.append((a, b, dr._ohms(node.get("value")) or 10000.0, nid))
        elif k == "button":
            a, b = g.net(nid, "A"), g.net(nid, "B")
            if a is not None and b is not None:
                self.buttons[nid] = (a, b)
                self.stimuli.append({"id": nid, "kind": "button", "event": True, "rest": 0, "active": 1, "hold": 0.3, "sustained": False})
        elif kind == "led":
            a, c = (g.net(nid, "A"), g.net(nid, "K")) if k == "led" else (g.net_of(nid, dr.ANODE), g.net_of(nid, dr.CATHODE))
            if a is not None and c is not None:
                text = f"{node.get('color') or ''} {g.text(nid)}"
                vf = next((v for rx, v in dr.LED_VF if rx.search(text)), dr.VF_MIN)
                self.diodes.append((a, c, vf, nid))
                self.outputs[nid] = "led"
        elif k == "diode" or kind == "diode":
            e = g.ends(nid)
            if e and e[0] is not None and e[1] is not None:
                self.diodes.append((e[0], e[1], 0.4, nid))
        elif kind in dr.SWITCHES:
            roles, _ = g.roles(nid)
            kk = "npn" if kind == "transistor" else kind
            if roles:
                if kk in ("npn", "pnp"):
                    b, e, c = (g.net(nid, roles[r][0]) for r in "BEC")
                    if None not in (b, e, c):
                        self.bjts.append((kk, b, e, c, nid))
                else:
                    gt, s, d = (g.net(nid, roles[r][0]) for r in "GSD")
                    if None not in (gt, s, d):
                        self.mos.append((kk, gt, s, d, nid))
        elif kind in ("buzzer", "buzzer_active", "buzzer_passive", "speaker", "motor", "relay"):
            two = self._two(nid)
            if two:
                ma = g.current_ma(nid) or LOAD_MA[kind]
                self.loads[nid] = {"a": two[0], "b": two[1], "ma": ma, "two": True}
                self.outputs[nid] = kind
        elif k == "accessory":
            self._accessory(nid, g.acc(nid))
        elif k == "chip":
            self._chip(nid, kind)
        elif k == "header" and any(fc._I2C_PIN.match(p["label"]) for p, _ in g.wired(nid)):
            self.i2c_any = True     # whatever is plugged in there answers

    def _accessory(self, nid: str, acc: dict[str, Any]) -> None:
        g, kind, sim = self.g, acc.get("kind"), acc.get("sim") or {}
        if kind == "battery":
            self.on_battery, self.battery = True, nid
            self.capacity_mah = float(acc.get("capacity_mah") or 0)
            return
        ma = float(acc.get("current_ma") or 0)
        if kind == "display":
            self._load(nid, ma, sleep_ma=float(acc.get("sleep_ma") or 0.02), display=True)
            self.outputs[nid] = "display"
            addr = int(str(acc.get("i2c_addr") or "0x3C"), 16)
            self.displays[addr] = nid
            self.keeps_image = self.keeps_image or bool(acc.get("keeps_image"))
            self.i2c.add(addr)
            return
        if sim.get("type") == "contact":
            a, b = g.net(nid, device.ident(sim["pin"])), g.net(nid, device.ident(sim["to"]))
            if a is not None and b is not None:
                self.contacts[nid] = (a, b, float(sim["ohm"]))
                self.stimuli.append({"id": nid, "kind": "contact", "event": True, "rest": 0, "active": 1, "hold": 20.0, "sustained": True})
            return
        self._load(nid, ma)
        if sim.get("type") == "bus":
            # a library's value, not a voltage: the runtime reads the channel (firmware_sim/libs.inc)
            self.buses.add(nid)
            if acc.get("i2c_addr"):
                self.i2c.add(int(str(acc["i2c_addr"]), 16))
            if sim.get("channel") is not None:
                self.stimuli.append({"id": nid, "kind": "bus_event", "event": True, "rest": 0, "active": 1, "hold": float(sim.get("hold", 2.0)), "sustained": False, "channel": sim["channel"]}
                                    if sim.get("event") else {"id": nid, "kind": "bus_value", "event": False, "rest": float(sim["rest"]), "values": list(sim["values"]), "channel": sim["channel"]})
        if sim.get("type") in ("analog", "digital"):
            out = g.net(nid, device.ident(sim["pin"]))
            load = self.loads.get(nid)
            if out is not None:
                self.sources[nid] = {"net": out, "vcc": load["a"] if load else None, "gnd": load["b"] if load else None,
                                     "rest": sim["rest_mv"], "active": sim["active_mv"], "r": float(sim.get("ohm", 1000.0))}
                if sim["type"] == "digital":
                    self.stimuli.append({"id": nid, "kind": "motion", "event": True, "rest": 0, "active": 1, "hold": 3.0, "sustained": True})
                else:
                    self.stimuli.append({"id": nid, "kind": "analog", "event": False, "rest": 0, "active": 1, "values": [0, 1]})
        if acc.get("kind") == "module" and "servo" in str(acc.get("name", "")).lower():
            self.outputs[nid] = "servo"
        elif acc.get("kind") == "module" and "relay" in str(acc.get("name", "")).lower():
            self.outputs[nid] = "relay"

    def _chip(self, nid: str, kind: str) -> None:
        g = self.g
        text = f"{g.text(nid)} {g.nodes[nid].get('label') or ''}"
        if g.addressable(nid):
            self._load(nid, 0.7, addressable=True)
            self.outputs[nid] = "rgb_led"
            return
        if dr.DIVIDER.search(text):
            two = self._two(nid)
            if two:
                if dr.THERMAL.search(text):
                    self.ntc[nid] = two
                    self.stimuli.append({"id": nid, "kind": "temp", "event": False, "rest": 25.0, "values": [10.0, 40.0]})
                else:
                    self.ldr[nid] = two
                    self.stimuli.append({"id": nid, "kind": "light", "event": False, "rest": 200.0, "values": [0.05, 800.0]})
            return
        self._load(nid, g.current_ma(nid) or 1.0)
        if PIR.search(text):
            load = self.loads.get(nid)
            out = next((net for p, net in g.wired(nid) if not g.power(net)), None)
            if out is not None:
                self.sources[nid] = {"net": out, "vcc": load["a"] if load else None, "gnd": load["b"] if load else None,
                                     "rest": 0, "active": 3300, "r": 1000.0}
                self.stimuli.append({"id": nid, "kind": "motion", "event": True, "rest": 0, "active": 1, "hold": 3.0, "sustained": True})
            return
        if I2C_LIGHT.search(text):
            self.i2c_any = True
            self.stimuli.append({"id": nid, "kind": "bus_light", "event": False, "rest": 200.0, "values": [0.05, 800.0], "channel": 0})
        elif I2C_CLIMATE.search(text):
            self.i2c_any = True
            self.stimuli.append({"id": nid, "kind": "bus_temp", "event": False, "rest": 25.0, "values": [10.0, 40.0], "channel": 1})
        elif any(fc._I2C_PIN.match(dr.catalog.base_label(p["label"])) for p, _ in g.wired(nid)):
            self.i2c_any = True

    # ---- solving
    def solve(self, env: dict[str, Any], states: dict[int, int], display: frozenset = frozenset(), inject: tuple[int, float] | None = None,
              lux_extra: float = 0.0) -> dict[str, Any]:
        n = self.n
        if not n:
            return {"v": np.zeros(0), "loads": {}, "rail_ma": 0.0, "gpio_ma": {}}
        diode_on = {i: False for i in range(len(self.diodes))}
        base_on = {i: False for i in range(len(self.bjts))}
        mos_on = {i: False for i in range(len(self.mos))}
        src_on = {nid: True for nid in self.sources}
        v = np.zeros(n)
        for _ in range(16):
            G, I = np.eye(n) * GMIN, np.zeros(n)

            def stamp(a: int, b: int | None, r: float) -> None:
                c = 1.0 / r
                G[a, a] += c
                if b is not None:
                    G[b, b] += c
                    G[a, b] -= c
                    G[b, a] -= c

            def drive(a: int, volts: float, r: float) -> None:
                stamp(a, None, r)
                I[a] += volts / r

            for i in self.grounds:
                drive(i, 0.0, GND_R)
            for i, volts in self.rails:
                if not (self.on_battery and volts >= 4.5):    # V5 is USB's: dead on a cell
                    drive(i, volts, RAIL_R)
            for gp, s in states.items():
                net = self.gpio_net.get(gp)
                if net is not None and s:
                    drive(net, 3.3 if s == 2 else 0.0, GPIO_R)
            for a, b, r, _ in self.res:
                if a != b:
                    stamp(a, b, r)
            for nid, (a, b) in self.buttons.items():
                if env.get(nid) and a != b:
                    stamp(a, b, 0.1)
            for nid, (a, b, ohm) in self.contacts.items():
                if env.get(nid) and a != b:
                    stamp(a, b, ohm)
            for nid, (a, b) in self.ldr.items():
                lux = max(float(env.get(nid, 200.0)) + lux_extra, 0.05)
                stamp(a, b, min(max(15000.0 * (10.0 / lux) ** 0.7, 800.0), 2e6))
            for nid, (a, b) in self.ntc.items():
                t = float(env.get(nid, 25.0)) + 273.15
                stamp(a, b, 10000.0 * float(np.exp(3950.0 * (1.0 / t - 1.0 / 298.15))))
            for nid, ld in self.loads.items():
                if ld["a"] != ld["b"]:
                    ma = ld["ma"]
                    if ld.get("display") and nid not in display:
                        ma = ld["sleep_ma"]
                    stamp(ld["a"], ld["b"], 3.3 / (ma / 1000.0))
            for nid, s in self.sources.items():
                if src_on[nid]:
                    val = float(env.get(nid) or 0)
                    mv = val if val > 1 else s["active"] if val else s["rest"]    # 0 / 1 are its two states, more is millivolts
                    stamp(s["net"], s["gnd"], s["r"])
                    I[s["net"]] += mv / 1000.0 / s["r"]
                    if s["gnd"] is not None:
                        I[s["gnd"]] -= mv / 1000.0 / s["r"]
            for i, (a, c, vf, _) in enumerate(self.diodes):
                if diode_on[i]:
                    stamp(a, c, 10.0)
                    I[a] += vf / 10.0
                    I[c] -= vf / 10.0
            for i, (kk, b, e, c, _) in enumerate(self.bjts):
                if base_on[i]:
                    x, y = (b, e) if kk == "npn" else (e, b)
                    stamp(x, y, 50.0)
                    I[x] += 0.7 / 50.0
                    I[y] -= 0.7 / 50.0
                    stamp(c, e, 2.0)
            for i, (kk, gt, s, d, _) in enumerate(self.mos):
                if mos_on[i]:
                    stamp(d, s, 0.2)
            if inject:
                I[inject[0]] -= inject[1]
            try:
                v = np.linalg.solve(G, I)
            except np.linalg.LinAlgError:
                v = np.linalg.lstsq(G, I, rcond=None)[0]
            changed = False
            for i, (a, c, vf, _) in enumerate(self.diodes):
                on = v[a] - v[c] > vf + (0.0 if diode_on[i] else 0.01)
                changed |= on != diode_on[i]
                diode_on[i] = on
            for i, (kk, b, e, c, _) in enumerate(self.bjts):
                x, y = (b, e) if kk == "npn" else (e, b)
                on = v[x] - v[y] > 0.7 + (0.0 if base_on[i] else 0.01)
                changed |= on != base_on[i]
                base_on[i] = on
            for i, (kk, gt, s, d, _) in enumerate(self.mos):
                on = (v[gt] - v[s] if kk == "nmos" else v[s] - v[gt]) > 1.8
                changed |= on != mos_on[i]
                mos_on[i] = on
            for nid, s in self.sources.items():
                on = s["vcc"] is None or (s["gnd"] is not None and v[s["vcc"]] - v[s["gnd"]] > 2.0)
                changed |= on != src_on[nid]
                src_on[nid] = on
            if not changed:
                break
        loads: dict[str, float] = {}
        for i, (a, c, vf, nid) in enumerate(self.diodes):
            if nid in self.outputs:
                loads[nid] = (v[a] - v[c] - vf) / 10.0 * 1000.0 if diode_on[i] else 0.0
        for nid, ld in self.loads.items():
            ma = ld["ma"]
            if ld.get("display") and nid not in display:
                ma = ld["sleep_ma"]
            loads[nid] = abs(v[ld["a"]] - v[ld["b"]]) / (3.3 / (ma / 1000.0)) * 1000.0
        rail = 0.0
        for i, volts in self.rails:
            if not (self.on_battery and volts >= 4.5):
                rail += (volts - v[i]) / RAIL_R * 1000.0
        gpio_ma: dict[int, float] = {}
        for gp, s in states.items():
            net = self.gpio_net.get(gp)
            if net is not None and s:
                ma = ((3.3 if s == 2 else 0.0) - v[net]) / GPIO_R * 1000.0
                gpio_ma[gp] = ma
                if s == 2:
                    rail += ma
        return {"v": v, "loads": loads, "rail_ma": rail, "gpio_ma": gpio_ma}

    def thevenin(self, gp: int, env: dict[str, Any], states: dict[int, int], display: frozenset = frozenset()) -> tuple[int, int | None]:
        """(open-circuit mV, source ohms or None when nothing drives it) of an input pin, the other pins as they are. A light
        sensor also sees the device's own lit LEDs."""
        net = self.gpio_net.get(gp)
        if net is None:
            return 0, None
        key = ("th", gp, tuple(sorted((k, v) for k, v in env.items() if k in self._env_keys)), tuple(sorted(states.items())), display)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        rest = {g: s for g, s in states.items() if g != gp and s}
        extra = 0.0
        if self.ldr:
            lit = self.solve(env, rest, display)["loads"]
            extra = sum(max(ma, 0.0) for nid, ma in lit.items() if self.outputs.get(nid) == "led") * 8.0
        a = self.solve(env, rest, display, lux_extra=extra)["v"][net]
        b = self.solve(env, rest, display, inject=(net, 20e-6), lux_extra=extra)["v"][net]
        r = (a - b) / 20e-6
        out = (int(round(max(a, 0.0) * 1000)), None if r > FLOATING_OHM else int(round(max(r, 1.0))))
        self._cache[key] = out
        return out

    @property
    def _env_keys(self) -> set[str]:
        return {s["id"] for s in self.stimuli}

    def level(self, env: dict[str, Any], states: dict[int, int], display: frozenset) -> dict[str, Any]:
        key = ("lv", tuple(sorted((k, v) for k, v in env.items() if k in self._env_keys)), tuple(sorted(states.items())), display)
        hit = self._cache.get(key)
        if hit is None:
            hit = self._cache[key] = self.solve(env, states, display)
        return hit


def g_kind(g: Any, nid: str) -> str:
    return g.kind.get(nid) or g.nodes[nid].get("kind") or ""


# ------------------------------------------------------------------ the scenarios
def _env_default(c: Circuit) -> dict[str, Any]:
    return {s["id"]: s["rest"] for s in c.stimuli}


def scenarios(c: Circuit) -> list[dict[str, Any]]:
    """What the graph alone says to try: each condition (light, soil, temperature...) with each event (press, motion, water)."""
    levels = [s for s in c.stimuli if not s["event"]][:2]
    events = [s for s in c.stimuli if s["event"]]
    contexts: list[dict[str, Any]] = [{}]
    for s in levels:
        contexts = [{**ctx, s["id"]: v} for ctx in contexts for v in s["values"]]
    out: list[dict[str, Any]] = []
    for ctx in contexts:
        name = ",".join(f"{k}={v}" for k, v in ctx.items())
        out.append({"name": f"baseline {name}".strip(), "ctx": ctx, "changes": [], "horizon": HORIZON_S, "kind": "baseline"})
        for s in events:
            hold = s["hold"]
            changes = [(PRESS_AT_S, s["id"], s["active"]), (PRESS_AT_S + hold, s["id"], s["rest"]),
                       (SECOND_AT_S, s["id"], s["active"]), (SECOND_AT_S + hold, s["id"], s["rest"])]
            out.append({"name": f"{s['id']} {s['kind']} {name}".strip(), "ctx": ctx, "changes": changes, "horizon": HORIZON_S,
                        "kind": "event", "stim": s["id"]})
    for s in events:
        for ctx in contexts[:2]:
            out.append({"name": f"{s['id']} once, then a long wait {','.join(f'{k}={v}' for k, v in ctx.items())}".strip(), "ctx": ctx,
                        "changes": [(5.0, s["id"], s["active"]), (5.0 + s["hold"], s["id"], s["rest"])], "horizon": LONG_S, "kind": "long", "stim": s["id"]})
    for s in events:
        if s["sustained"]:
            for ctx in contexts[:2]:
                out.append({"name": f"{s['id']} stays active {','.join(f'{k}={v}' for k, v in ctx.items())}".strip(), "ctx": ctx,
                            "changes": [(10.0, s["id"], s["active"])], "horizon": STUCK_S, "kind": "stuck", "stim": s["id"]})
        else:
            out.append({"name": f"{s['id']} held at power-on", "ctx": contexts[0], "changes": [(8.0, s["id"], s["rest"])],
                        "start": {s["id"]: s["active"]}, "horizon": 30.0, "kind": "boot_hold", "stim": s["id"]})
    out.append({"name": "left alone", "ctx": contexts[0], "changes": [], "horizon": IDLE_S if c.on_battery else 3600.0, "kind": "idle",
                "fuel": IDLE_FUEL})
    return out[:MAX_RUNS]


def followups(c: Circuit, runs: list[tuple[dict[str, Any], dict[str, Any]]]) -> list[dict[str, Any]]:
    """An input that did nothing alone may act only while another does (a brightness button while the light is on): try it with
    each sustained input held."""
    out: list[dict[str, Any]] = []
    for s in c.stimuli:
        if not s["event"] or _effect_of(c, s, runs):
            continue
        if s["kind"] == "button":     # a long press does what a click does not
            for ctx in {tuple(sorted(r["sc"]["ctx"].items())) for r, _ in runs if r["sc"]["kind"] == "baseline"}:
                out.append({"name": f"{s['id']} held 4 s {dict(ctx) or ''}".strip(), "ctx": dict(ctx), "horizon": HORIZON_S, "kind": "event", "stim": s["id"],
                            "changes": [(PRESS_AT_S, s["id"], s["active"]), (PRESS_AT_S + 4.0, s["id"], s["rest"])]})
        for o in c.stimuli:
            if o is s or not o["event"] or not o["sustained"] or not _effect_of(c, o, runs):
                continue
            ctx = next((r["sc"]["ctx"] for r, tl in runs if r["sc"].get("stim") == o["id"] and r["sc"]["kind"] == "event" and _diff(tl, _baseline(runs, r["sc"]["ctx"]))), {})
            hold = (10.0, o["id"], o["active"])
            tag = f"with {o['id']} active"
            out.append({"name": f"baseline {tag}", "ctx": ctx, "changes": [hold], "horizon": HORIZON_S, "kind": "pair_base", "with": o["id"]})
            out.append({"name": f"{s['id']} {s['kind']} {tag}", "ctx": ctx, "horizon": HORIZON_S, "kind": "pair", "stim": s["id"], "with": o["id"],
                        "changes": [hold, (PRESS_AT_S, s["id"], s["active"]), (PRESS_AT_S + s["hold"], s["id"], s["rest"])]})
    return out[:12]


def _baseline(runs: list, ctx: dict[str, Any]) -> dict[str, Any]:
    return next(tl for r, tl in runs if r["sc"]["kind"] == "baseline" and r["sc"]["ctx"] == ctx)


def _effect_of(c: Circuit, s: dict[str, Any], runs: list) -> set[str]:
    """What this input changes: against the same run without it."""
    changed: set[str] = set()
    for r, tl in runs:
        k = r["sc"]["kind"]
        if s["event"] and r["sc"].get("stim") == s["id"] and k == "event":
            changed |= _diff(tl, _baseline(runs, r["sc"]["ctx"]))
        elif s["event"] and r["sc"].get("stim") == s["id"] and k == "pair":
            base = next((t2 for r2, t2 in runs if r2["sc"]["kind"] == "pair_base" and r2["sc"]["with"] == r["sc"]["with"] and r2["sc"]["ctx"] == r["sc"]["ctx"]), None)
            if base is not None:
                changed |= _diff(tl, base)
        elif not s["event"] and k == "baseline":
            for r2, tl2 in runs:
                if r2["sc"]["kind"] == "baseline" and _differ_only_in(r["sc"]["ctx"], r2["sc"]["ctx"], s["id"]):
                    changed |= _diff(tl, tl2)
    if not s["event"] and not changed:     # a condition may only matter when an event comes (dark + motion)
        for r, tl in runs:
            if r["sc"]["kind"] == "event":
                for r2, tl2 in runs:
                    if r2["sc"]["kind"] == "event" and r2["sc"].get("stim") == r["sc"].get("stim") and _differ_only_in(r["sc"]["ctx"], r2["sc"]["ctx"], s["id"]):
                        changed |= _diff(tl, tl2)
    return changed


# ------------------------------------------------------------------ running: wasmtime
class NotModelled(Exception):
    pass


def _demangle(sym: str) -> str:
    """'_ZN9WiFiClass5beginEPKc' -> 'WiFiClass::begin'; enough to name a call to the designer."""
    if not sym.startswith("_Z"):
        return sym
    names = []
    i = 3 if sym.startswith("_ZN") else 2
    while i < len(sym) and sym[i] in "KRV":
        i += 1
    while i < len(sym) and sym[i].isdigit():
        m = re.match(r"\d+", sym[i:])
        n = int(m.group())
        i += len(m.group())
        names.append(sym[i:i + n])
        i += n
    return "::".join(names) or sym


_ENGINE: Any = None


def _engine() -> Any:
    global _ENGINE
    if _ENGINE is None:
        import wasmtime
        cfg = wasmtime.Config()
        cfg.consume_fuel = True
        _ENGINE = wasmtime.Engine(cfg)
    return _ENGINE


class Machine:
    """One compiled firmware on one circuit; run() is one scenario, boot after boot."""

    def __init__(self, wasm: bytes, circuit: Circuit, tmp: str) -> None:
        import wasmtime
        self.w, self.c, self.tmp = wasmtime, circuit, tmp
        self.module = wasmtime.Module(_engine(), wasm)
        self.cur: dict[str, Any] = {}
        self.linker = self._link()

    def _link(self) -> Any:
        w, c = self.w, self.c
        linker = w.Linker(_engine())
        linker.define_wasi()
        adc = ADC_FULL_MV.get(c.mcu, 2500)
        i32, i64 = w.ValType.i32(), w.ValType.i64()
        ft = w.FuncType

        def pin(caller: Any, gp: int, t: int, ptr: int) -> int:
            mem = caller["memory"]
            raw = mem.read(caller, ptr, ptr + 64 * 4)
            states = {g: raw[g * 4] for g in c.gpio_net if raw[g * 4]}
            states = {g: (2 if s == 3 else s) for g, s in states.items()}
            mv, r = c.thevenin(gp, self.env_at(t), states, self.cur["display"])
            return (mv << 32) | (0xffffffff if r is None else min(r, 0xfffffffe))

        def next_env(t: int) -> int:
            times = self.cur["times"]
            i = bisect_right(times, t)
            return times[i] if i < len(times) else -1

        def env(ch: int, t: int) -> int:
            stim = next((s for s in c.stimuli if s.get("channel") == ch), None)
            defaults = {0: 200.0, 1: 25.0, 2: 45.0, 3: 101325.0, 4: 0.0, 5: 0.0, 6: 0.0, 7: 1.0, 8: 0.0}
            val = self.env_at(t).get(stim["id"], stim["rest"]) if stim else defaults.get(ch, 0.0)
            return int(val * 100) if ch != 3 else int(val)

        def rtc_load(caller: Any, p: int, n: int) -> None:
            data = self.cur.get("rtc")
            if data and len(data) == n:
                caller["memory"].write(caller, data, p)

        def rtc_save(caller: Any, p: int, n: int) -> None:
            self.cur["rtc"] = bytes(caller["memory"].read(caller, p, p + n))

        def slept(wake: int, cause: int, mask: int) -> None:
            self.cur["wake"] = (wake, cause, mask)

        def has_i2c(addr: int) -> int:
            return 1 if addr in c.i2c or c.i2c_any else 0

        d = linker.define_func
        d("sim", "pin", ft([i32, i64, i32], [i64]), pin, access_caller=True)
        d("sim", "next_env", ft([i64], [i64]), next_env)
        d("sim", "env", ft([i32, i64], [i32]), env)
        d("sim", "boot_t", ft([], [i64]), lambda: self.cur["boot_t"])
        d("sim", "boot_n", ft([], [i32]), lambda: self.cur["boot_n"])
        d("sim", "boot_cause", ft([], [i32]), lambda: self.cur["cause"])
        d("sim", "boot_mask", ft([], [i64]), lambda: self.cur["mask"])
        d("sim", "end_t", ft([], [i64]), lambda: self.cur["end_t"])
        d("sim", "adc_full", ft([], [i32]), lambda: adc)
        d("sim", "has_i2c", ft([i32], [i32]), has_i2c)
        d("sim", "rtc_load", ft([i32, i32], []), rtc_load, access_caller=True)
        d("sim", "rtc_save", ft([i32, i32], []), rtc_save, access_caller=True)
        d("sim", "slept", ft([i64, i32, i64], []), slept)

        def nvs_load(caller: Any, p: int) -> None:
            caller["memory"].write(caller, self.cur.get("nvs") or b"", p)

        def nvs_save(caller: Any, p: int, n: int) -> None:
            self.cur["nvs"] = bytes(caller["memory"].read(caller, p, p + n))

        d("sim", "nvs_size", ft([], [i32]), lambda: len(self.cur.get("nvs") or b""))
        d("sim", "nvs_load", ft([i32], []), nvs_load, access_caller=True)
        d("sim", "nvs_save", ft([i32, i32], []), nvs_save, access_caller=True)
        for imp in self.module.imports:
            if imp.module == "env":
                name = _demangle(imp.name)

                def trap(*_: Any, n: str = name) -> Any:
                    raise NotModelled(n)

                d(imp.module, imp.name, imp.type, trap)
        return linker

    def env_at(self, t: int) -> dict[str, Any]:
        table = self.cur["envs"]
        return table[bisect_right(self.cur["times"], t)]

    def _boot(self, fuel: int) -> tuple[int | str, list[str], int, int]:
        """One power-on to its end: (exit code or what stopped it, log lines, fuel left, the clock when it stopped)."""
        w, cur = self.w, self.cur
        path = os.path.join(self.tmp, f"out{os.getpid()}_{id(cur)}_{cur['boot_n']}.txt")
        store = w.Store(_engine())
        wc = w.WasiConfig()
        wc.stdout_file = path
        store.set_wasi(wc)
        store.set_fuel(max(fuel, 1))
        inst = self.linker.instantiate(store, self.module)
        ex = inst.exports(store)
        how: int | str = "returned"
        try:
            ex["_start"](store)
        except w.ExitTrap as e:
            how = e.code
        except NotModelled as e:
            how = f"call:{e}"
        except w.Trap as e:
            how = "fuel" if "fuel" in str(e) else f"trap:{str(e)[:120]}"
        except w.WasmtimeError as e:
            how = "fuel" if "fuel" in str(e) else f"trap:{str(e)[:120]}"
        left = 0
        try:
            left = store.get_fuel()
        except Exception:  # noqa: BLE001
            left = 0
        now = cur["boot_t"]
        if isinstance(how, str):
            try:
                store.set_fuel(2_000_000)
                now = ex["sim_now"](store)
                ex["sim_flush"](store)
            except Exception:  # noqa: BLE001 - a trapped instance tells nothing more
                pass
        lines: list[str] = []
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                lines = f.read().splitlines()
            os.unlink(path)
        return how, lines, left, now

    def run(self, sc: dict[str, Any]) -> dict[str, Any]:
        c = self.c
        base = {**_env_default(c), **(sc.get("ctx") or {}), **(sc.get("start") or {})}
        changes = sorted(sc.get("changes") or [], key=lambda x: x[0])
        times, envs = [], [dict(base)]
        for t, sid, val in changes:
            times.append(int(t * 1e6))
            envs.append({**envs[-1], sid: val})
        end_t = int(sc["horizon"] * 1e6)
        self.cur = {"times": times, "envs": envs, "end_t": end_t, "boot_t": 0, "boot_n": 1, "cause": 0, "mask": 0, "display": frozenset(), "rtc": None}
        fuel = int(sc.get("fuel") or SCENARIO_FUEL)
        events: list[str] = []
        stop: str | None = None
        now = 0
        sleeps: list[dict[str, Any]] = []
        lit: set[int] = set()
        while True:
            self.cur["wake"] = None
            how, lines, left, at = self._boot(fuel)
            events += lines
            fuel = left
            now = at
            for ln in lines:      # a display keeps what it was told across the chip's sleep
                if ln.startswith("L "):
                    p = ln.split()
                    (lit.add if p[3] == "1" else lit.discard)(int(p[2]))
            self.cur["display"] = frozenset(c.displays[a] for a in lit if a in c.displays)
            if how == EXIT_SLEPT and self.cur["wake"]:
                wake, cause, mask = self.cur["wake"]
                sleeps.append({"at": _sleep_time(lines), "wake": wake, "cause": cause, "mask": mask})
                if wake < 0 or wake + 120000 >= end_t:
                    now = end_t
                    break
                self.cur["boot_t"] = wake + 120000
                self.cur["boot_n"] += 1
                self.cur["cause"], self.cur["mask"] = cause, mask
                if self.cur["boot_n"] > BOOT_LIMIT:
                    stop = "boots"
                    now = wake
                    break
                continue
            if how == EXIT_RESTART:
                self.cur["boot_t"] = at + 300000
                self.cur["boot_n"] += 1
                self.cur["cause"], self.cur["mask"] = 0, 0
                if self.cur["boot_n"] > BOOT_LIMIT:
                    stop = "boots"
                    break
                continue
            if how == EXIT_END:
                now = end_t
            elif isinstance(how, str):
                stop = how
            else:
                stop = f"exit:{how}"
            break
        return {"sc": sc, "events": events, "stop": stop, "end": now, "sleeps": sleeps, "boots": self.cur["boot_n"]}


def _sleep_time(lines: list[str]) -> int:
    for ln in reversed(lines):
        if ln.startswith("M ") and ln.endswith(" deep"):
            return int(ln.split()[1])
    return 0


# ------------------------------------------------------------------ reading a run
def timeline(c: Circuit, run: dict[str, Any]) -> dict[str, Any]:
    """The event log through the circuit: on-time and charge per load, what the battery gave, by power state."""
    sc = run["sc"]
    base = {**_env_default(c), **(sc.get("ctx") or {}), **(sc.get("start") or {})}
    env_changes = sorted(((int(t * 1e6), s, v) for t, s, v in sc.get("changes") or []), key=lambda x: x[0])
    env = dict(base)
    states: dict[int, int] = {}
    duty: dict[int, float] = {}
    tones: dict[int, int] = {}
    lit: set[int] = set()
    mode, t = "active", 0
    active_ma, light_ma, deep_ma = MCU_MA.get(c.mcu, (25.0, 1.0, 0.1))
    on: dict[str, float] = {}
    spans: dict[str, list[list[float]]] = {}
    charge: dict[str, float] = {}
    by_mode = {"active": 0.0, "light": 0.0, "deep": 0.0}
    mode_s = {"active": 0.0, "light": 0.0, "deep": 0.0}
    deep_loads: dict[str, float] = {}
    gpio_peak: dict[int, float] = {}
    frames: list[tuple[float, int, str]] = []
    serial: list[tuple[float, str]] = []
    neo_ma: dict[str, float] = {}
    rgb = [k for k, v in c.outputs.items() if v == "rgb_led"]
    radio = False
    warned: list[tuple[float, str, str]] = []
    screen_power: list[tuple[float, bool]] = []
    driven: dict[int, set[int]] = {}
    sound: dict[str, float] = {}

    def levels() -> tuple[dict[str, float], float]:
        disp = frozenset(c.displays[a] for a in lit if a in c.displays)
        plain = {g: s for g, s in states.items() if s in (1, 2)}
        pwm = {g: (duty.get(g, 0.0) if s == 3 and g not in tones else 0.5) for g, s in states.items() if s == 3}
        lo = c.level(env, {**plain, **{g: 1 for g in pwm}}, disp)
        loads, rail = dict(lo["loads"]), lo["rail_ma"]
        for g, m in lo["gpio_ma"].items():
            gpio_peak[g] = max(gpio_peak.get(g, 0.0), abs(m))
        for g, d in pwm.items():
            hi = c.level(env, {**plain, **{x: 1 for x in pwm if x != g}, g: 2}, disp)
            gpio_peak[g] = max(gpio_peak.get(g, 0.0), abs(hi["gpio_ma"].get(g, 0.0)))
            for k, v in hi["loads"].items():
                loads[k] = loads.get(k, 0.0) + d * (v - lo["loads"].get(k, 0.0))
            rail += d * (hi["rail_ma"] - lo["rail_ma"])
        return loads, rail

    def close(until: int) -> None:
        nonlocal t
        if until <= t:
            return
        dt = (until - t) / 1e6
        loads, rail = levels()
        mcu = {"active": active_ma, "light": light_ma, "deep": deep_ma}[mode]
        total = max(rail, 0.0) + mcu + (RADIO_MA if radio and mode == "active" else 0.0)
        for k, ma in neo_ma.items():
            if loads.get(k, 0.0) > 0.1:
                total += ma
                loads[k] = loads.get(k, 0.0) + ma
                on[k] = on.get(k, 0.0) + dt
                sp = spans.setdefault(k, [])
                if sp and t / 1e6 - sp[-1][1] < 0.02:
                    sp[-1][1] = until / 1e6
                elif len(sp) < 2000:
                    sp.append([t / 1e6, until / 1e6])
        by_mode[mode] += total * dt
        mode_s[mode] += dt
        for k, ma in loads.items():
            charge[k] = charge.get(k, 0.0) + ma * dt
            if mode == "deep":
                deep_loads[k] = deep_loads.get(k, 0.0) + ma * dt
            kind = c.outputs.get(k)
            if kind and _is_on(c, k, ma, tones, states):
                on[k] = on.get(k, 0.0) + dt
                sp = spans.setdefault(k, [])
                t0, t1 = t / 1e6, until / 1e6
                if sp and t0 - sp[-1][1] < 0.02:
                    sp[-1][1] = t1
                elif len(sp) < 2000:
                    sp.append([t0, t1])
        t = until

    def advance_to(when: int) -> None:
        nonlocal env_changes, env
        while env_changes and env_changes[0][0] <= when:
            at, sid, val = env_changes[0]
            close(at)
            env = {**env, sid: val}
            env_changes = env_changes[1:]
        close(when)

    for ln in run["events"]:
        p = ln.split(" ", 2)
        if len(p) < 2 or not p[1].lstrip("-").isdigit():
            continue
        kind, when = p[0], int(p[1])
        rest = p[2] if len(p) > 2 else ""
        if kind not in ("O", "B", "M", "L", "F", "S", "X", "W", "N"):
            continue
        advance_to(when)
        if kind == "O":
            q = rest.split()
            g, code, val = int(q[0]), q[1], int(q[2])
            driven.setdefault(g, set())
            if code == "Z":
                states[g] = 0
                tones.pop(g, None)
            elif code == "D":
                states[g] = 2 if val else 1
                tones.pop(g, None)
                driven[g].add(val)
            elif code == "P":
                states[g] = 3
                duty[g] = val / 1000.0
                tones.pop(g, None)
                driven[g].add(1 if val else 0)
            elif code == "T":
                states[g] = 3 if val else 0
                if val:
                    tones[g] = val
                    driven[g].add(1)
                else:
                    tones.pop(g, None)
        elif kind == "M":
            mode = {"deep": "deep", "light": "light", "wake": "active"}[rest.strip()]
        elif kind == "B":
            mode = "active"
            states, duty, tones = {}, {}, {}
            radio = False
        elif kind == "L":
            q = rest.split()
            (lit.add if q[1] == "1" else lit.discard)(int(q[0]))
            # e-paper keeps its picture with its power off: asleep it draws nothing and still shows what it last drew
            if not c.keeps_image:
                screen_power.append((when / 1e6, q[1] == "1"))
        elif kind == "F":
            q = rest.split(" ", 1)
            frames.append((when / 1e6, int(q[0]), q[1] if len(q) > 1 else ""))
        elif kind == "S":
            if len(serial) < 400:
                serial.append((when / 1e6, rest))
        elif kind == "X":
            q = rest.split()
            cols = q[2].split(",") if len(q) >= 3 else []
            for i, k in enumerate(rgb):        # the chain in id order: what the graph's own order would say
                col = cols[i] if i < len(cols) else "000000"
                ma = sum(int(col[j:j + 2], 16) for j in (0, 2, 4)) / 255.0 * 12.0
                if ma > 0:
                    neo_ma[k] = ma
                else:
                    neo_ma.pop(k, None)
        elif kind == "N":
            radio = rest.strip() == "1"
        elif kind == "W":
            q = rest.split(" ", 1)
            warned.append((when / 1e6, q[0], q[1] if len(q) > 1 else ""))
    end = run["end"]
    advance_to(end)
    span = max(end / 1e6, 1e-6)
    return {"on": on, "spans": spans, "charge": charge, "by_mode": by_mode, "mode_s": mode_s, "deep_loads": deep_loads, "gpio_peak": gpio_peak,
            "frames": frames, "screen_power": screen_power, "serial": serial, "warned": warned, "driven": driven, "avg_ma": sum(by_mode.values()) / span, "span": span}


def _is_on(c: Circuit, nid: str, ma: float, tones: dict[int, int], states: dict[int, int]) -> bool:
    kind, ld = c.outputs[nid], c.loads.get(nid)
    if kind == "rgb_led":
        return False      # by what was shown (timeline), not by its idle draw
    if kind == "led":
        return ma > 0.05
    if kind == "buzzer_passive" or kind == "speaker":
        return bool(tones) and ma > 0.02 * (ld["ma"] if ld else 1)  # DC only clicks: it sounds while a tone reaches it
    if kind == "display":
        return ld is not None and ma > ld["sleep_ma"] * 3
    if ld:
        return ma > 0.2 * ld["ma"]
    return ma > 0.05


def _fmt_t(s: float) -> str:
    return f"{s:.1f} s" if s < 600 else f"{s / 60:.1f} min" if s < 7200 else f"{s / 3600:.1f} h"


def trace_text(c: Circuit, run: dict[str, Any], tl: dict[str, Any], limit: int = 14) -> str:
    """What happened in a run, for the designer: loads turning on and off, the screen, sleeps."""
    rows: list[tuple[float, str]] = [(t / 1.0, f"{sid} -> {val}") for t, sid, val in run["sc"].get("changes") or []]
    for nid, sp in tl["spans"].items():
        for a, b in sp[:6]:
            rows.append((a, f"{nid} on for {_fmt_t(b - a)}" if b > a else f"{nid} shows"))
    for t, _, txt in tl["frames"][:8]:
        rows.append((t, f"screen: {txt[:70]}"))
    for s in run["sleeps"][:10]:
        w = s["wake"]
        rows.append((s["at"] / 1e6, "deep sleep" + (f", woke at {_fmt_t(w / 1e6)} by "
                     + ("timer" if s["cause"] == 4 else _mask_names(c, s["mask"])) if w >= 0 else ", to the end of this run")))
    rows.sort(key=lambda r: r[0])
    return "; ".join(f"t={_fmt_t(t)}: {what}" for t, what in rows[:limit]) + ("; ..." if len(rows) > limit else "")


def _mask_names(c: Circuit, mask: int) -> str:
    return ", ".join(_pin_name(c, g) for g in range(64) if mask >> g & 1) or "a pin"


def _pin_name(c: Circuit, g: int) -> str:
    return f"{c.module}.{c.gpio_label[g]} (GPIO{g})" if g in c.gpio_label else f"GPIO{g}"


def _f(sev: str, code: str, ref: str, msg: str, hint: str = "", trace: str = "") -> dict[str, Any]:
    out = {"code": code, "severity": sev, "ref": ref, "msg": msg}
    if hint:
        out["hint"] = hint
    if trace:
        out["trace"] = trace[:700]
    return out


# ------------------------------------------------------------------ a requirement's test
TEST_HOLD_S = 0.3
TEST_MAX = 12
TEST_RUN_S = 3600.0


def test_steps(steps: Any, known: dict[str, dict[str, Any]]) -> tuple[list[tuple[float, str, Any]], str | None]:
    """A test's steps as a scenario's changes: {at_s, press: 'SW1', hold_s?} presses and lets go, {at_s, input, value} sets a value."""
    out: list[tuple[float, str, Any]] = []
    for x in steps if isinstance(steps, list) else []:
        if not isinstance(x, dict) or not isinstance(x.get("at_s"), (int, float)):
            return [], f"a step needs at_s: {str(x)[:80]}"
        at = float(x["at_s"])
        sid = x.get("press") or x.get("input")
        stim = known.get(str(sid))
        if not stim:
            return [], f"no input {sid}: the inputs are " + (", ".join(f"{k} ({v['kind']})" for k, v in known.items()) or "none")
        if x.get("press"):
            if not stim["event"]:
                return [], f"{sid} ({stim['kind']}) is no button: give it a value with input"
            hold = float(x["hold_s"]) if isinstance(x.get("hold_s"), (int, float)) else TEST_HOLD_S
            out += [(at, stim["id"], stim["active"]), (at + hold, stim["id"], stim["rest"])]
        else:
            if "value" not in x and not stim["event"]:
                return [], f"{sid} ({stim['kind']}) needs a value"
            out.append((at, stim["id"], x.get("value", stim.get("active", 1))))
    return sorted(out, key=lambda c: c[0]), None


def _test_invalid(c: Circuit, test: dict[str, Any], known: dict[str, dict[str, Any]]) -> str | None:
    expect = test.get("expect")
    if not isinstance(expect, list) or not expect:
        return "a test needs expect: what must follow"
    for k in (test.get("given") or {}):
        if k not in known:
            return f"given names {k}: the inputs are " + (", ".join(known) or "none")
    for e in expect:
        if not isinstance(e, dict):
            return f"an expect is an object: {str(e)[:80]}"
        if not isinstance(e.get("at_s"), (int, float)) and not (isinstance(e.get("from_s"), (int, float)) and isinstance(e.get("to_s"), (int, float))):
            return f"an expect needs at_s or from_s and to_s: {str(e)[:80]}"
        if "output" in e and e["output"] not in c.outputs:
            return f"no output {e['output']}: the outputs are " + (", ".join(c.outputs) or "none")
        if not any(k in e for k in ("output", "screen", "not_screen", "asleep")):
            return f"an expect says output, screen, not_screen or asleep: {str(e)[:80]}"
    return None


def test_targets(test: Any) -> set[str]:
    """What a test checks, whatever the moment: which output on or off, the screen, the chip asleep."""
    out: set[str] = set()
    for e in (test.get("expect") if isinstance(test, dict) else None) or []:
        if not isinstance(e, dict):
            continue
        if "output" in e:
            out.add(f"{e['output']} {'on' if e.get('on', True) else 'off'}")
        if "screen" in e:
            out.add("the screen")
        if "not_screen" in e:
            out.add("what the screen must not show")
        if "asleep" in e:
            out.add("the chip asleep" if e["asleep"] else "the chip awake")
    return out


def _screen_at(tl: dict[str, Any], t: float) -> str | None:
    """What the display shows at t: its last frame, None while it is off."""
    off = False
    for at, on in tl["screen_power"]:
        if at <= t:
            off = not on
    if off:
        return None
    last = None
    for at, _, text in tl["frames"]:
        if at <= t + 0.03:
            last = text
    return last


def _screens_in(tl: dict[str, Any], a: float, b: float) -> list[str]:
    seen = [x for x in [_screen_at(tl, a)] if x is not None]
    seen += [text for at, _, text in tl["frames"] if a <= at <= b]
    return seen


def _asleep_at(run: dict[str, Any], t: float) -> bool:
    return any(s["at"] / 1e6 <= t and (s["wake"] < 0 or t < s["wake"] / 1e6) for s in run["sleeps"])


def _expect_fail(run: dict[str, Any], tl: dict[str, Any], e: dict[str, Any]) -> str | None:
    """Why this expectation failed in this run, or None. A window with on true wants it on at some moment (a beep counts), with
    on false off throughout; at_s is that very moment."""
    a = float(e["at_s"] if "at_s" in e else e["from_s"])
    b = float(e["at_s"] if "at_s" in e else e["to_s"])
    when = f"at t={a:g} s" if a == b else f"between {a:g} and {b:g} s"
    if a > tl["span"]:
        return f"the run ended at {_fmt_t(tl['span'])}, before {when}"
    if "output" in e:
        nid, want = e["output"], e.get("on", True)
        spans = tl["spans"].get(nid) or []
        lit = any(s0 <= b + 0.02 and s1 >= a - 0.02 for s0, s1 in spans)
        if bool(want) != lit:
            return f"{nid} should be {'on' if want else 'off'} {when}, and it is {'on' if lit else 'off'}"
    if "screen" in e:
        want = str(e["screen"]).lower()
        seen = _screens_in(tl, a, b)
        if not any(want in x.lower() for x in seen):
            return f"the screen should show '{e['screen']}' {when}, and it shows: " + (" / ".join(dict.fromkeys(seen[:4])) or "nothing")
    if "not_screen" in e:
        want = str(e["not_screen"]).lower()
        seen = _screens_in(tl, a, b)
        if any(want in x.lower() for x in seen):
            return f"the screen should not show '{e['not_screen']}' {when}, and it does"
    if "asleep" in e and bool(e["asleep"]) != _asleep_at(run, a):
        return f"the chip should be {'asleep' if e['asleep'] else 'awake'} at t={a:g} s, and it is not"
    return None


def _test_scenario(test: dict[str, Any], changes: list[tuple[float, str, Any]], rid: str) -> dict[str, Any]:
    last = max([float(e.get("to_s", e.get("at_s", 0))) for e in test["expect"]] + [t for t, _, _ in changes])
    return {"name": f"{rid} test", "ctx": dict(test.get("given") or {}), "changes": changes, "horizon": min(last + 5.0, TEST_RUN_S), "kind": "test", "fuel": 3 * SCENARIO_FUEL}


def run_tests(machine: Machine, c: Circuit, doc: dict[str, Any], t0: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Each requirement's test, played: (findings, one result per requirement with firmware work). A passing test with a positive
    expectation is played again without its steps: if it still passes, nothing the person did caused what it checks."""
    found: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    known = {s["id"]: s for s in c.stimuli}
    played = 0
    for r in doc.get("requirements") or []:
        if not isinstance(r, dict):
            continue
        rid, test = str(r.get("id")), r.get("test")
        if not isinstance(test, dict):
            if r.get("firmware"):
                results.append({"id": rid, "status": "no_test"})
            continue
        changes, bad = test_steps(test.get("steps"), known)
        bad = bad or _test_invalid(c, test, known)
        if bad:
            found.append(_f("error", "sim_test_invalid", rid, f"the test of {rid} cannot be played: {bad}"))
            results.append({"id": rid, "status": "invalid"})
            continue
        if played >= TEST_MAX or time.monotonic() - t0 > WALL_S:
            results.append({"id": rid, "status": "skipped"})
            continue
        played += 1
        sc = _test_scenario(test, changes, rid)
        run, tl = _run(machine, c, sc)
        if str(run["stop"] or "").startswith("call:"):
            results.append({"id": rid, "status": "not_modelled"})
            continue
        fails = [x for x in (_expect_fail(run, tl, e) for e in test["expect"]) if x]
        if fails:
            found.append(_f("error", "sim_requirement_failed", rid, f"{rid} ('{str(r.get('text'))[:90]}') fails its test: " + "; ".join(fails[:3]),
                            "fix the firmware or the board so the device does this; the requirement is the person's", trace_text(c, run, tl, 24)))
            results.append({"id": rid, "status": "failed", "why": fails[:3]})
            continue
        positive = [e for e in test["expect"] if ("output" in e and e.get("on", True)) or "screen" in e or e.get("asleep")]
        if changes and positive:
            idle, idle_tl = _run(machine, c, {**sc, "changes": [], "name": f"{rid} test without its steps"})
            if not any(_expect_fail(idle, idle_tl, e) for e in test["expect"]):
                found.append(_f("error", "sim_test_vacuous", rid, f"the test of {rid} also passes with its steps removed: what it checks happens whatever the person does, "
                                "so it proves nothing", "expect what the steps cause, at a moment it would not be true without them"))
                results.append({"id": rid, "status": "vacuous"})
                continue
        results.append({"id": rid, "status": "passed"})
    return found, results


# ------------------------------------------------------------------ the invariants
def judge(c: Circuit, runs: list[tuple[dict[str, Any], dict[str, Any]]], doc: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    found: list[dict[str, Any]] = []
    reqs = [r for r in doc.get("requirements") or [] if isinstance(r, dict)]
    fw_parts = {p for r in reqs if r.get("firmware") for p in r.get("parts") or []}
    calls = sorted({r["stop"][5:] for r, _ in runs if str(r["stop"]).startswith("call:")})
    blocked = bool(calls)
    if calls:
        found.append(_f("warning", "sim_not_modelled", "firmware", "the simulator has no model of " + ", ".join(calls[:6]) +
                        ": the run stopped at that call, so what comes after it was not exercised"))
    for r, tl in runs:
        stop = str(r["stop"] or "")
        if stop == "fuel":
            if r["sc"]["kind"] != "idle" and r.get("stuck"):
                found.append(_f("error", "sim_hang", "firmware", f"in '{r['sc']['name']}' the firmware stops making progress at "
                                f"t={_fmt_t(r['end'] / 1e6)}: it spins without delay() or millis() and nothing can end the loop",
                                "a loop waiting on a pin or a flag must also have a way out", trace_text(c, r, tl)))
        elif stop.startswith("trap:"):
            found.append(_f("error", "sim_crash", "firmware", f"in '{r['sc']['name']}' the firmware crashes at t={_fmt_t(r['end'] / 1e6)}: {stop[5:]}",
                            "an out-of-range array index, a null pointer or a division by zero", trace_text(c, r, tl)))
        if r["boots"] > 20 and r["end"] / 1e6 / r["boots"] < BOOT_LOOP_S:
            found.append(_f("error", "sim_boot_loop", "firmware", f"in '{r['sc']['name']}' the chip restarts over and over ({r['boots']} boots in "
                            f"{_fmt_t(r['end'] / 1e6)})", "it must stay asleep or running until something changes", trace_text(c, r, tl)))
    # sleep that does not sleep: the wake level is already there when it goes to sleep, with nothing having changed
    seen: set[tuple] = set()
    for r, tl in runs:
        if r["sc"]["kind"] not in ("stuck", "idle"):
            continue
        for s in r["sleeps"]:
            if s["wake"] < 0 or s["cause"] == 4 or s["wake"] - s["at"] > 1_000_000:
                continue
            key = (r["sc"].get("stim"), s["mask"])
            if key in seen:
                continue
            seen.add(key)
            names = _mask_names(c, s["mask"])
            stim = r["sc"].get("stim")
            found.append(_f("error", "sim_sleep_rearms", str(stim or "firmware"),
                            f"with {stim or 'an input'} staying active the firmware goes to deep sleep at t={_fmt_t(s['at'] / 1e6)} and wakes at once: "
                            f"{names} is still at its wake level, and a level wake fires immediately, so the device repeats itself instead of "
                            "sleeping, a reset cannot end it, and the cell drains",
                            "before sleeping, take a pin that is still active out of the wake mask (wake on the button and a timer, and look at "
                            "that input again on the timer), keeping what was already reported in RTC_DATA_ATTR", trace_text(c, r, tl)))
    # read from a pin nothing sets
    floats: dict[int, tuple[float, str]] = {}
    mids: dict[int, tuple[int, str]] = {}
    absent: set[str] = set()
    raw_i2c = False
    for r, tl in runs:
        for t, code, detail in tl["warned"]:
            raw_i2c = raw_i2c or code == "i2c_raw_read"
            q = detail.split()
            if code == "float_read" and q:
                floats.setdefault(int(q[0]), (t, r["sc"]["name"]))
            elif code == "mid_level" and len(q) > 1:
                mids.setdefault(int(q[0]), (int(q[1]), r["sc"]["name"]))
            elif code in ("i2c_absent",) and q:
                absent.add(q[0])
    for g, (t, name) in floats.items():
        who = c.unmodelled.get(g)
        if who:
            found.append(_f("warning", "sim_input_not_modelled", who, f"{_pin_name(c, g)} reads {who}, which the simulator has no signal model for: "
                            "the firmware saw a floating pin there, so its reaction to that part was not exercised"))
        else:
            found.append(_f("error", "sim_float_read", _pin_name(c, g), f"the firmware reads {_pin_name(c, g)} while nothing sets its level "
                            f"(in '{name}' at t={_fmt_t(t)}): no pull-up in pinMode and none on the board, so it reads noise",
                            "INPUT_PULLUP in pinMode, or a resistor to the rail"))
    for g, (mv, name) in mids.items():
        net = c.gpio_net.get(g)
        contact = next((nid for nid, (a, b, _) in c.contacts.items() if net in (a, b)), None)
        found.append(_f("error" if contact else "warning", "sim_mid_level", contact or _pin_name(c, g), f"in '{name}' {_pin_name(c, g)} sits at {mv} mV, between a logic low and a logic high "
                        "(below 825 mV and above 2475 mV are safe): the reading is undefined",
                        "a weaker pull-up widens what reads as active (one pull only, not INPUT_PULLUP over a resistor), or read it with analogRead"))
    for a in absent:
        found.append(_f("error", "sim_i2c_absent", f"0x{int(a):02X}", f"the firmware talks to I2C address 0x{int(a):02X}, and nothing on this board answers there",
                        "the part's address from its card"))
    # overloaded pins
    peak: dict[int, float] = {}
    for _, tl in runs:
        for g, ma in tl["gpio_peak"].items():
            peak[g] = max(peak.get(g, 0.0), ma)
    for g, ma in peak.items():
        if ma > GPIO_ABS_MA:
            found.append(_f("error", "sim_gpio_overload", _pin_name(c, g), f"{_pin_name(c, g)} has to carry {ma:.0f} mA, over the {GPIO_ABS_MA:.0f} mA a pin survives",
                            "drive that load through a transistor"))
    # outputs that never turn on
    union_on: dict[str, float] = {}
    for _, tl in runs:
        for k, v in tl["on"].items():
            union_on[k] = max(union_on.get(k, 0.0), v)
    if not blocked:
        for nid, kind in c.outputs.items():
            if union_on.get(nid, 0.0) > 0 or kind == "servo":
                continue
            sev, why = _dead_reason(c, nid, runs)
            found.append(_f(sev, "sim_output_dead" if sev == "error" else "sim_output_not_reached", nid, f"{nid} ({kind}) never turns on in any run: {why}",
                            "", trace_text(c, *runs[-1])))
    # inputs that change nothing
    effects: dict[str, list[str]] = {}
    for s in c.stimuli:
        changed = _effect_of(c, s, runs)
        effects[s["id"]] = sorted(changed)
        if not changed and s.get("channel") is not None and raw_i2c:
            found.append(_f("warning", "sim_input_not_modelled", s["id"], f"the firmware reads {s['id']} with raw Wire calls, and the simulator models that part only through "
                            "its library: its reaction to this input was not exercised", "the part's library makes this checkable"))
        elif not changed and not blocked:
            sev = "error" if s["id"] in fw_parts else "warning"
            found.append(_f(sev, "sim_input_no_effect", s["id"], f"{s['id']} ({s['kind']}) changes nothing: in every condition tried, the outputs, the screen "
                            "and the serial log are the same with it as without it", "check the pin it is wired to against the firmware, and the condition the firmware waits for"))
    # the power budget, from the run left alone
    power = _power(c, runs, reqs, found)
    cover = {"scenarios": len(runs), "simulated_s": round(sum(tl["span"] for _, tl in runs)), "not_modelled": calls,
             "inputs": {s["id"]: s["kind"] for s in c.stimuli}, "outputs": c.outputs}
    found.sort(key=lambda f: f["severity"] != "error")
    return found, {"effects": effects, "power": power}, cover


def _differ_only_in(a: dict, b: dict, key: str) -> bool:
    return a.get(key) != b.get(key) and all(a[k] == b.get(k) for k in a if k != key)


def _diff(a: dict[str, Any], b: dict[str, Any]) -> set[str]:
    """What differs between two runs: time on, how bright or loud (the charge it took), the screen, the log."""
    out = {k for k in set(a["on"]) | set(b["on"]) if abs(a["on"].get(k, 0.0) - b["on"].get(k, 0.0)) > 0.05}
    for k in set(a["on"]) | set(b["on"]):
        x, y = a["charge"].get(k, 0.0), b["charge"].get(k, 0.0)
        if abs(x - y) > max(0.03 * max(x, y), 0.01):
            out.add(k)
    if {f[2] for f in a["frames"]} != {f[2] for f in b["frames"]}:
        out.add("screen")
    if {s[1] for s in a["serial"]} != {s[1] for s in b["serial"]}:
        out.add("serial")
    return out


def _rgb_dead(c: Circuit, nid: str) -> tuple[str, str]:
    powered = c.solve(_env_default(c), {}, frozenset())["loads"].get(nid, 0.0) > 0.1
    if not powered:
        rails = "; on the cell V5 is dead (it is USB's 5 V)" if c.on_battery else ""
        return "error", f"it has no supply in this circuit{rails}"
    return "warning", "the firmware's show() never gives it a colour in the runs tried (is the count in the constructor the chain's length?)"


def _dead_reason(c: Circuit, nid: str, runs: list) -> tuple[str, str]:
    """(severity, why): the circuit cannot do it (reversed, a rail that is dead, nothing driving it) or the firmware never takes the
    pin; a firmware that holds the pin and did not get there in these runs may only need a sequence nobody tried."""
    if c.outputs[nid] == "rgb_led":
        return _rgb_dead(c, nid)
    disp = frozenset(c.displays.values())
    env = _env_default(c)
    can: list[int] = []
    for g in c.gpio_net:
        lo = c.solve(env, {g: 1}, disp)["loads"].get(nid, 0.0)
        hi = c.solve(env, {g: 2}, disp)["loads"].get(nid, 0.0)
        if abs(hi - lo) > 0.05:
            can.append(g)
    idle = c.solve(env, {}, disp)["loads"].get(nid, 0.0)
    if not can and idle <= 0.05:
        rails = "; on the cell V5 is dead (it is USB's 5 V)" if c.on_battery else ""
        return "error", f"no pin of the module can make current flow through it in this circuit (reversed, or its supply is missing{rails})"
    if not can:
        return "warning", f"it draws {idle:.1f} mA whatever the pins do, and is never seen active"
    driven: dict[int, set[int]] = {}
    for _, tl in runs:
        for g, vals in tl["driven"].items():
            driven.setdefault(g, set()).update(vals)
    names = ", ".join(_pin_name(c, g) for g in can)
    if not any(g in driven for g in can):
        return "error", f"{names} can drive it, but the firmware never makes that pin an output (pinMode OUTPUT / ledcAttach) in any run"
    return "warning", f"{names} can drive it, and in the runs tried (each input pressed, each condition, half an hour) the firmware never sets the level that turns it on"


def _power(c: Circuit, runs: list, reqs: list[dict[str, Any]], found: list[dict[str, Any]]) -> dict[str, Any]:
    idle = next(((r, tl) for r, tl in runs if r["sc"]["kind"] == "idle"), None)
    out: dict[str, Any] = {"on_battery": c.on_battery, "capacity_mah": c.capacity_mah or None}
    if not idle:
        return out
    r, tl = idle
    if str(r["stop"] or "").startswith("call:"):
        return out
    out["idle_avg_ma"] = round(float(tl["avg_ma"]), 3)
    out["simulated_s"] = round(tl["span"])
    out["peak_avg_ma"] = round(float(max(t["avg_ma"] for _, t in runs)), 1)
    deep = tl["mode_s"]["deep"]
    if deep > 0:
        floor = float(tl["by_mode"]["deep"]) / deep
        out["sleep_ma"] = round(floor, 3)
        tops = sorted(((k, float(q) / deep) for k, q in tl["deep_loads"].items() if q / deep > 0.005), key=lambda x: -x[1])[:4]
        out["sleep_top"] = [{"part": k, "ma": round(v, 3)} for k, v in tops]
    if c.on_battery and c.capacity_mah:
        life_h = c.capacity_mah / max(float(tl["avg_ma"]), 1e-4)
        out["idle_life_h"] = round(life_h, 1)
        if deep > 0 and out["sleep_ma"] > SLEEP_FLOOR_MA:
            tops = ", ".join(f"{t['part']} {t['ma']:.1f} mA" for t in out["sleep_top"]) or "the rail"
            found.append(_f("error", "sim_sleep_draw", (out["sleep_top"] or [{"part": "board"}])[0]["part"],
                            f"asleep the device still draws {out['sleep_ma']:.2f} mA ({tops}), so the {c.capacity_mah:.0f} mAh cell lasts {_life(life_h)} left alone, "
                            "however deep the chip sleeps: V3V3 stays up in deep sleep",
                            "power that part from a GPIO (it can give 20 mA) or through a transistor, on only while it is read"))
        asks = next((x for x in reqs if fc.asks_sleep(str(x.get("text") or ""))), None)
        if asks and deep <= 0 and not str(r["stop"] or "").startswith("call:"):
            found.append(_f("error", "sim_never_sleeps", "firmware", f"{asks.get('id')} asks for sleep, and left alone for {_fmt_t(tl['span'])} the firmware never sleeps: "
                            f"{tl['avg_ma']:.1f} mA, so the cell lasts {_life(life_h)}", "go to sleep after a while with nothing to do", trace_text(c, r, tl)))
    return out


def _life(h: float) -> str:
    return f"{h:.0f} hours" if h < 72 else f"{h / 24:.0f} days" if h < 24 * 90 else f"{h / 24 / 30:.0f} months"


# ------------------------------------------------------------------ building
_MODULES: dict[str, bytes] = {}
_LOCK = asyncio.Lock()


def _zig_env() -> dict[str, str]:
    cache = os.path.join(tempfile.gettempdir(), "iamodelize3d-zig")
    return {**os.environ, "ZIG_GLOBAL_CACHE_DIR": cache, "ZIG_LOCAL_CACHE_DIR": cache}


def _defs(board: fc.Board) -> list[str]:
    b = board.spec
    return ["-DFW_SIM", "-DARDUINO=10819", *[f"-D{d}" for d in b.get("defs") or []], f"-D{b['define']}"]


def _zig(args: list[str], cwd: str, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "ziglang", "c++", "--target=wasm32-wasi", *args], cwd=cwd, env=_zig_env(), capture_output=True,
                          timeout=timeout, check=False, text=True, errors="replace")


def _runtime_object(board: fc.Board) -> str:
    h = hashlib.sha1(RUNTIME.read_bytes())
    for name in ("libs.inc", "libs_auto.inc"):
        h.update((RUNTIME.parent / name).read_bytes())
    for f in sorted(STUBS.rglob("*.h")):
        h.update(f.read_bytes())
    cache = os.path.join(tempfile.gettempdir(), "iamodelize3d-zig")
    os.makedirs(cache, exist_ok=True)
    obj = os.path.join(cache, f"runtime-{board.mpn}-{h.hexdigest()[:12]}.o")
    if not os.path.exists(obj):
        tmp = f"{obj}.{os.getpid()}"
        p = _zig(["-O1", "-std=gnu++17", "-fno-exceptions", "-w", "-I", str(STUBS), *_defs(board), "-c", "-o", tmp, str(RUNTIME)], cache, COMPILE_S)
        if p.returncode:
            raise RuntimeError(f"runtime build failed: {p.stderr[-400:]}")
        os.replace(tmp, obj)
    return obj


def compile_sketch(board: fc.Board, files: dict[str, str]) -> tuple[bytes | None, str]:
    """The sketch and the virtual board as one WebAssembly module; (None, why) when it cannot be built. A sketch never sees more
    than the firmware check lets it include, and no inline assembly (.incbin would read the server's files)."""
    cc = {n: t.replace("\r\n", "\n") for n, t in files.items() if n.endswith(fc.CPP_EXT)}
    if not cc:
        return None, "no C++ files"
    key = hashlib.sha1(repr((board.mpn, sorted(cc.items()), RUNTIME.stat().st_mtime)).encode()).hexdigest()
    if key in _MODULES:
        return _MODULES[key], ""
    srcs = {n: fc.Src(n, t) for n, t in cc.items()}
    if fc._unsafe_includes(srcs.values()):
        return None, "an include outside the sketch"
    order = fc._sketch_order([n for n in cc if n.endswith(".ino")], cc)
    gen, _ = fc._generated(cc, list(srcs.values()))
    with tempfile.TemporaryDirectory(prefix="fwsim-", ignore_cleanup_errors=True) as tmp:
        sketch, genroot = Path(tmp) / "sketch", Path(tmp) / "gen"
        sketch.mkdir()
        genroot.mkdir()
        for rel, text in gen.items():
            p = genroot / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        units = []
        for n, t in cc.items():
            if not n.endswith(".ino"):
                (sketch / n).write_text(t, encoding="utf-8")
                if n.endswith((".cpp", ".cc", ".cxx")):
                    units.append(n)
        if order:
            unit = f"{Path(order[0]).stem}__sketch.ino.cpp"
            (sketch / unit).write_text(fc._merge(order, cc, srcs), encoding="utf-8")
            units.insert(0, unit)
        if not units:
            return None, "nothing to compile"
        common = ["-std=gnu++17", "-fno-exceptions", "-w", "-I", str(genroot), "-I", str(STUBS), *_defs(board)]
        for u in units:
            p = _zig(["-E", *common, u], str(sketch), COMPILE_S)
            if p.returncode:
                return None, f"preprocess failed: {p.stderr[-300:]}"
            mine = False
            for ln in p.stdout.splitlines():
                if ln.startswith("#"):
                    m = re.match(r'#\s*(?:line\s+)?\d+\s+"([^"]+)"', ln)
                    if m:
                        mine = os.path.isabs(m.group(1)) is False or "fwsim-" in m.group(1)
                        mine = mine and "firmware_stubs" not in m.group(1) and "ziglang" not in m.group(1)
                elif mine and ASM.search(ln):
                    return None, "inline assembly in the sketch"
        out = Path(tmp) / "fw.wasm"
        p = _zig(["-O1", *common, "-Wl,--import-symbols", "-o", str(out), *units, _runtime_object(board)], str(sketch), COMPILE_S)
        if p.returncode or not out.exists():
            miss = re.findall(r"undefined symbol: (\S+)", p.stderr) + re.findall(r"undefined data symbol[^\n]*?(\w+)$", p.stderr, re.M)
            if miss:
                return None, "not modelled: " + ", ".join(sorted({_demangle(m) for m in miss})[:6])
            return None, f"build failed: {p.stderr[-400:]}"
        data = out.read_bytes()
    _MODULES[key] = data
    if len(_MODULES) > 32:
        _MODULES.pop(next(iter(_MODULES)))
    return data, ""


# ------------------------------------------------------------------ entry
def _simulate(doc: dict[str, Any], parts: dict[str, dict[str, Any]], files: dict[str, str]) -> dict[str, Any]:
    t0 = time.monotonic()
    board = fc.Board.of(doc)
    if not board or board.mpn not in BOARDS:
        return {"ran": False, "ok": True, "why": f"no simulator for {board.name if board else 'a device without a module'} yet"}
    try:
        import wasmtime  # noqa: F401
        import ziglang  # noqa: F401
    except ImportError:
        return {"ran": False, "ok": True, "why": "no WebAssembly toolchain on this server"}
    wasm, why = compile_sketch(board, files)
    if wasm is None:
        return {"ran": False, "ok": True, "why": why}
    circuit = Circuit(doc, parts)
    runs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    with tempfile.TemporaryDirectory(prefix="fwsimrun-", ignore_cleanup_errors=True) as tmp:
        machine = Machine(wasm, circuit, tmp)
        skipped = 0
        for sc in scenarios(circuit):
            if time.monotonic() - t0 > WALL_S:
                skipped += 1
                continue
            runs.append(_run(machine, circuit, sc))
        for sc in followups(circuit, runs):
            if time.monotonic() - t0 > WALL_S:
                skipped += 1
                continue
            runs.append(_run(machine, circuit, sc))
        test_found, tests = run_tests(machine, circuit, doc, t0)
    found, facts, cover = judge(circuit, runs, doc)
    cover["skipped"] = skipped
    cover["tests"] = {st: sum(1 for x in tests if x["status"] == st) for st in {x["status"] for x in tests}}
    found = sorted(test_found + found, key=lambda f: f["severity"] != "error")
    facts["requirements"] = tests
    errors = [f for f in found if f["severity"] == "error"]
    return {"ran": True, "ok": not errors, "findings": found[:14], **facts, "coverage": cover,
            "scenarios": [{"name": r["sc"]["name"], "kind": r["sc"]["kind"], "end_s": round(tl["span"], 1), "boots": r["boots"],
                           "stop": r["stop"], "trace": trace_text(circuit, r, tl, 8)} for r, tl in runs][:MAX_RUNS],
            "ms": int((time.monotonic() - t0) * 1000)}


def _run(machine: Machine, c: Circuit, sc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """One scenario, read. Out of fuel twice at the same moment is a hang; further along it was only a long run."""
    run = machine.run(sc)
    if run["stop"] == "fuel":
        again = machine.run({**sc, "fuel": 2 * int(sc.get("fuel") or SCENARIO_FUEL)})
        again["stuck"] = again["stop"] == "fuel" and again["end"] <= run["end"]
        run = again
    return run, timeline(c, run)


def _try(doc: dict[str, Any], parts: dict[str, dict[str, Any]], files: dict[str, str], steps: list[dict[str, Any]], horizon: float,
         condition: dict[str, Any]) -> dict[str, Any]:
    board = fc.Board.of(doc)
    if not board or board.mpn not in BOARDS:
        return {"ran": False, "why": f"no simulator for {board.name if board else 'a device without a module'} yet"}
    wasm, why = compile_sketch(board, files)
    if wasm is None:
        return {"ran": False, "why": why}
    c = Circuit(doc, parts)
    known = {s["id"]: s for s in c.stimuli}
    changes, why = test_steps(steps, known)
    bad = [str(k) for k in condition if k not in known]
    if why or bad:
        return {"ran": False, "why": why or f"no input {', '.join(bad[:4])}: the inputs are " + (", ".join(f"{k} ({v['kind']})" for k, v in known.items()) or "none")}
    end = min(max(float(horizon or 0.0), max((t for t, _, _ in changes), default=0.0) + 30.0), IDLE_S)
    sc = {"name": "your scenario", "ctx": dict(condition), "changes": changes, "horizon": end, "kind": "custom", "fuel": IDLE_FUEL}
    with tempfile.TemporaryDirectory(prefix="fwsimrun-", ignore_cleanup_errors=True) as tmp:
        run = Machine(wasm, c, tmp).run(sc)
    tl = timeline(c, run)
    return {"ran": True, "stop": run["stop"], "end_s": round(tl["span"], 1), "boots": run["boots"], "trace": trace_text(c, run, tl, 60),
            "on_s": {k: round(float(v), 1) for k, v in tl["on"].items()}, "screen": [f"{_fmt_t(t)}: {x}" for t, _, x in tl["frames"][:30]],
            "serial": [f"{_fmt_t(t)}: {x}" for t, x in tl["serial"][:30]], "avg_ma": round(float(tl["avg_ma"]), 2),
            "warnings": sorted({f"{code} {d}" for _, code, d in tl["warned"]})[:8]}


async def try_scenario(doc: dict[str, Any], parts: dict[str, dict[str, Any]], files: dict[str, str], steps: list[dict[str, Any]], horizon: float = 120.0,
                       condition: dict[str, Any] | None = None) -> dict[str, Any]:
    """One scenario of the designer's: inputs changing at given moments, the trace of what the device did."""
    try:
        async with _LOCK:
            return await asyncio.to_thread(_try, doc, parts, {str(k): str(v) for k, v in files.items()}, steps, horizon, condition or {})
    except Exception as e:  # noqa: BLE001
        log.exception("firmware scenario failed")
        return {"ran": False, "why": f"the simulator failed ({type(e).__name__}: {str(e)[:160]})"}


LIFE_WORD = re.compile(r"(\d+(?:[.,]\d+)?)(?:\s*[-–]\s*(\d+(?:[.,]\d+)?))?\s*(час|ч\b|h\b|hour|д(?:ень|ня|ней)|сут|day|недел|week|мес|month|год|лет|year)", re.I)
UNIT_H = (("час", 1), ("ч", 1), ("h", 1), ("д", 24), ("сут", 24), ("day", 24), ("недел", 168), ("week", 168), ("мес", 720), ("month", 720), ("год", 8760), ("лет", 8760), ("year", 8760))
BATTERY_TEXT = re.compile(r"батар|аккум|заряд|lipo|battery|cell|charge|\bсон\b|\bсне\b|ожидан|standby|sleep", re.I)


def battery_claims(text: str) -> list[tuple[str, float]]:
    """The battery lives a summary states: (the words, hours). Only a sentence about the battery, by its own words."""
    out = []
    for sent in re.split(r"(?<=[.;!?])\s+|\n", str(text or "")):
        if not BATTERY_TEXT.search(sent):
            continue
        for m in LIFE_WORD.finditer(sent):
            unit = m[3].lower()
            hours = next((h for u, h in UNIT_H if unit.startswith(u)), None)
            if hours:
                val = float((m[2] or m[1]).replace(",", "."))
                out.append((m[0], val * hours))
    return out


def life_text(hours: float) -> str:
    return _life(hours)


async def simulate(doc: dict[str, Any], parts: dict[str, dict[str, Any]], files: dict[str, str], lang: str = "arduino") -> dict[str, Any]:
    """The firmware on its circuit; never raises (a broken simulator is 'not simulated', never a verdict on the device)."""
    try:
        if "python" in str(lang).lower() or not any(str(n).endswith(fc.CPP_EXT) for n in files or {}):
            return {"ran": False, "ok": True, "why": "the simulator runs Arduino C++ only"}
        async with _LOCK:
            return await asyncio.to_thread(_simulate, doc, parts, {str(k): str(v) for k, v in files.items()})
    except Exception as e:  # noqa: BLE001
        log.exception("firmware simulation failed")
        return {"ran": False, "ok": True, "why": f"the simulator failed ({type(e).__name__}: {str(e)[:160]})"}
