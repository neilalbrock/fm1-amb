#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Record the stems build's USB audio input (EN_STEMS=1 ./build.sh) and check it:

  tools/uac_stems.py [SECONDS] [OUT.wav]      (default 60 s, build/stems.wav; pip3 install sounddevice numpy)

Ten channels: 1-2 the master, 3-4 the pad, 5-6 the bells, 7-8 the bass, 9-10 the pulse, the layers dry
(the echo and the plate are the master's alone). Writes them to a 16-bit WAV, says how loud each pair
is, and checks what can be checked without knowing the music: the bass is mono, so channels 7 and 8
must be the same in every frame (a frame cut short or shifted breaks that), and a packet the FM-1 ran
short of repeats its last frame, so a frame equal to the one before in all ten channels while anything
sounds is counted. The FM-1's own count of USB glitches is on its Setup page ("USB n").

Exits 0 when the checks pass, 1 when not, 2 when there is no stems build to record."""
import sys
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

NAME = "AMB-1"
RATE = 44100
PAIRS = [("master", 0), ("pad", 2), ("bells", 4), ("bass", 6), ("pulse", 8)]


def find():
    for i, d in enumerate(sd.query_devices()):
        if NAME in d["name"] and d["max_input_channels"] > 0:
            return i, d
    return None, None


def record(dev, seconds):
    blocks, flags = [], []

    def cb(indata, frames, t, status):
        blocks.append(indata.copy())
        if status:
            flags.append(str(status))

    with sd.InputStream(device=dev, channels=10, samplerate=RATE, dtype="float32", latency="high", callback=cb):
        sd.sleep(int(seconds * 1000))
    return np.concatenate(blocks), flags


def db(v):
    return f"{20 * np.log10(v):6.1f}" if v > 0 else "  -inf"


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "build/stems.wav")
    dev, info = find()
    if dev is None:
        print(f"no {NAME} audio input: is the FM-1 plugged in?")
        return 2
    if info["max_input_channels"] != 10:
        print(f"{info['name']}: {info['max_input_channels']} channels, not the stems build's 10 (EN_STEMS=1 ./build.sh)")
        return 2
    print(f"{info['name']}: 10 channels; recording {seconds:g} s")
    x, flags = record(dev, seconds)
    s = np.clip(np.rint(x * 32768.0), -32768, 32767).astype(np.int16)

    out.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out), "wb") as wf:
        wf.setnchannels(10)
        wf.setsampwidth(2)
        wf.setframerate(RATE)
        wf.writeframes(s.tobytes())

    print(f"  {len(s)} frames ({len(s) / RATE:.1f} s) -> {out}")
    print("               peak dBFS    rms dBFS")
    for name, c in PAIRS:
        pair = x[:, c:c + 2]
        peak = float(np.max(np.abs(pair))) if pair.size else 0.0
        rms = float(np.sqrt(np.mean(pair.astype(np.float64) ** 2))) if pair.size else 0.0
        print(f"  {c + 1:2}-{c + 2:<2} {name:7}   {db(peak)}      {db(rms)}")

    bass_split = int(np.sum(s[:, 6] != s[:, 7]))
    same = np.all(s[1:] == s[:-1], axis=1) & np.any(np.abs(s[1:]) >= 256, axis=1)   # sounding: above -42 dBFS
    frozen = int(np.sum(same))
    print(f"  bass frames where 7 and 8 differ: {bass_split}")
    print(f"  frames repeated in all ten channels while something sounds (above -42 dBFS): {frozen}")
    if frozen:
        t = np.flatnonzero(same)[:8] / RATE
        print("    first at " + ", ".join(f"{v:.3f} s" for v in t))
    if flags:
        print(f"  host input status (the recording here, not the FM-1): {sorted(set(flags))}")
    if np.max(np.abs(x[:, 2:])) == 0:
        print("FAIL: the layers are silent (is the garden playing?)")
        return 1
    if bass_split or frozen:
        print("FAIL")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
