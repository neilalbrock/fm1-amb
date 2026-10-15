#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""The USB audio packet-size probe: does the FM-1 send isochronous packets larger than the stereo
input's 184 bytes? Records the audio input of a probe build and checks every frame.

  EN_UAC_CH=10 ./build.sh && python3 tools/fm1_install.py build/amb.fwsc
  tools/uac_probe.py [SECONDS]              (default 30; pip3 install sounddevice numpy)

A probe build (firmware/src/usb.c, uac_spread) declares N channels (4..11), so each 1 ms packet is
44 or 45 frames of N 16-bit samples, declared for up to 46: 10 channels send 880/900 bytes (920
declared), 11 send 968/990 (1012; 1023 is full speed's most). Channels 1-2 are the master; each other channel c (0-based) carries frame << 4 | c, the frame
a count that wraps at 4096. A lost or repeated packet breaks the count; a packet cut short or a
sample shifted puts the wrong channel number in the low four bits.

Exits 0 when every frame came through, 1 when not, 2 when there is no probe build to record."""
import sys

import numpy as np
import sounddevice as sd

NAME = "AMB-1"
RATE = 44100


def find():
    for i, d in enumerate(sd.query_devices()):
        if NAME in d["name"] and d["max_input_channels"] > 0:
            return i, d
    return None, None


def record(dev, nch, seconds):
    blocks, flags = [], []

    def cb(indata, frames, t, status):
        blocks.append(indata.copy())
        if status:
            flags.append(str(status))

    with sd.InputStream(device=dev, channels=nch, samplerate=RATE, dtype="float32", latency="high",
                        callback=cb):
        sd.sleep(int(seconds * 1000))
    return np.concatenate(blocks), flags


def words(x, scale):
    return np.rint(x * scale).astype(np.int64) & 0xFFFF


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 30.0
    dev, info = find()
    if dev is None:
        print(f"no {NAME} audio input: is the FM-1 plugged in, with a build that has the USB audio input?")
        return 2
    nch = info["max_input_channels"]
    if nch < 4:
        print(f"{info['name']}: {nch} channels, the stereo build. Build the probe: EN_UAC_CH=10 ./build.sh")
        print("(if this is a probe build, the host has kept the old descriptors or refused the larger ones)")
        return 2
    print(f"{info['name']}: {nch} channels, packets of {44 * nch * 2}/{45 * nch * 2} bytes; recording {seconds:g} s")
    x, flags = record(dev, nch, seconds)

    # the host's float is the 16-bit sample over 32768 (Core Audio) or 32767: take the one that decodes
    probe = x[:, 2:]
    best = max((32768.0, 32767.0), key=lambda s: int(np.sum((words(probe[:RATE], s) & 0xF) ==
                                                              np.arange(2, nch))))
    w = words(probe, best)
    live = np.flatnonzero(np.any(w != 0, axis=1))   # before the stream starts the host hands silence
    if live.size == 0:
        print("FAIL: the counter channels are silent: no packet arrived")
        return 1
    w = w[live[0]:live[-1] + 1]
    n = len(w)

    wrong = np.any((w & 0xF) != np.arange(2, nch), axis=1)          # cut short or shifted
    seq = w >> 4
    split = np.any(seq != seq[:, :1], axis=1) & ~wrong              # the channels disagree on the frame
    good = ~(wrong | split)
    s = seq[:, 0]
    step = (s[1:] - s[:-1]) & 0xFFF
    # each break in the count: one frame out of place (the count carries on after it), a gap or a repeat
    events, skip = [], -1
    for i in np.flatnonzero(step != 1):
        if i <= skip or not (good[i] and good[i + 1]):
            continue
        if i + 2 < n and good[i + 2] and (s[i + 2] - s[i]) & 0xFFF == 2:
            events.append((i + 1, "stray", f"from {(s[i] + 1 - s[i + 1]) & 0xFFF} frames back (mod 4096)"))
            skip = i + 1
        elif step[i] == 0:
            events.append((i + 1, "repeat", ""))
        else:
            events.append((i + 1, "gap", f"{step[i] - 1} frames lost (mod 4096)"))
    kinds = [e[1] for e in events]
    lost = sum(int(step[f - 1]) - 1 for f, k, _ in events if k == "gap")

    master = x[live[0]:live[-1] + 1, :2]
    peak = float(np.max(np.abs(master))) if master.size else 0.0
    print(f"  {n} frames ({n / RATE:.1f} s) checked, samples read as /{best:.0f}")
    print(f"  frames with a wrong channel number: {int(np.sum(wrong))}")
    print(f"  frames where the channels disagree: {int(np.sum(split))}")
    print(f"  stray frames (one frame out of place, the count carrying on): {kinds.count('stray')}")
    print(f"  gaps: {kinds.count('gap')} ({lost} frames lost); repeats: {kinds.count('repeat')}")
    if peak > 0:
        print(f"  master (1-2): peak {20 * np.log10(peak):.1f} dBFS")
    else:
        print("  master (1-2): silent (MASTER down or the garden resting? if not, the FM-1 stopped feeding it)")
    if flags:
        print(f"  host input status (the recording here, not the FM-1): {sorted(set(flags))}")
    for i in np.flatnonzero(wrong | split)[:8]:
        print(f"    at {i / RATE:8.3f} s  wrong   {' '.join(f'{v:04x}' for v in w[i])}")
    for f, k, what in events[:24]:
        print(f"    at {f / RATE:8.3f} s  {k:6}  {' '.join(f'{v:04x}' for v in w[f])}  {what}")
    if events:
        t = np.array([f for f, _, _ in events]) / RATE
        print(f"  {len(events)} events between {t[0]:.3f} and {t[-1]:.3f} s"
              + (f", {1000 * np.median(np.diff(t)):.1f} ms apart (median)" if len(t) > 1 else ""))
    if events or np.any(~good):
        print("FAIL" + (" (the host reported input overflows: try again before blaming the packets)"
                        if flags else ""))
        return 1
    print("ok: every frame came through")
    return 0


if __name__ == "__main__":
    sys.exit(main())
