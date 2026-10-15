#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
"""Does the USB audio input disturb USB MIDI? Times the FM-1's MIDI clock with the audio stream idle,
then again while its every channel is recorded, and compares.

  tools/midi_clock_probe.py [SECONDS]        (default 60 a phase; pip3 install python-rtmidi sounddevice numpy)

The garden must be playing, on its own clock, with MIDI out on (Setup). The clock is 24 ticks a quarter
note; the FM-1 makes each on its sample in the render and sends it after the render's half (5.8 ms),
so some spread is the instrument's own, in both phases. Times are taken as the ticks reach this script
(time.perf_counter): python-rtmidi's Core MIDI deltas, summed, showed gaps of whole ticks that never
happened. The first 2 s of a phase are left out: a backlog arrives at once when the port opens.

Phase 1: nobody records the audio input, so the stream is idle (alt 0). Phase 2: all its channels are
recorded, so every 1 ms frame carries an isochronous packet beside the MIDI. For each phase: the ticks'
interval and the tempo it implies, their spread (standard deviation), the 99th percentile and the
worst deviation, and ticks missing (an interval over 1.5 times the mean)."""
import re
import sys
import time

import numpy as np
import rtmidi
import sounddevice as sd

PORT_RE = re.compile(r"fm-1|felucca|amb-1", re.I)


def open_port():
    m = rtmidi.MidiIn()
    for i, p in enumerate(m.get_ports()):
        if PORT_RE.search(p):
            m.open_port(i)
            m.ignore_types(sysex=True, timing=False, active_sense=True)
            return m, p
    return None, None


def listen(m, seconds):
    ticks = []

    def cb(event, data):
        msg, _ = event
        if msg and msg[0] == 0xF8:
            ticks.append(time.perf_counter())

    t0 = time.perf_counter()
    m.set_callback(cb)
    time.sleep(seconds + 2.0)
    m.cancel_callback()
    t = np.array(ticks)
    return np.diff(t[t > t0 + 2.0]) * 1000.0


def report(name, iv):
    if len(iv) < 24:
        print(f"  {name}: {len(iv) + 1 if len(iv) else 0} ticks: is the garden playing, with MIDI out on?")
        return None
    mean = float(np.mean(iv))
    dev = np.abs(iv - mean)
    missing = int(np.sum(iv > 1.5 * mean))
    sd_ms = float(np.std(iv))
    print(f"  {name}: {len(iv)} intervals, {mean:.3f} ms ({60000.0 / (mean * 24):.2f} bpm); spread {sd_ms:.2f} ms, "
          f"99% within {np.percentile(dev, 99):.2f} ms, worst {np.max(dev):.2f} ms; {missing} missing")
    return sd_ms, float(np.percentile(dev, 99)), missing


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 60.0
    m, port = open_port()
    if m is None:
        print("no FM-1 MIDI port")
        return 2
    dev = next((i for i, d in enumerate(sd.query_devices()) if "AMB-1" in d["name"] and d["max_input_channels"] > 0),
               None)
    if dev is None:
        print("no AMB-1 audio input: the second phase needs it")
        return 2
    nch = sd.query_devices(dev)["max_input_channels"]
    print(f"MIDI from {port}; audio input {nch} channels; {seconds:g} s a phase")

    print("phase 1: the audio stream idle")
    idle = report("idle     ", listen(m, seconds))
    print(f"phase 2: recording all {nch} channels")
    with sd.InputStream(device=dev, channels=nch, samplerate=44100, dtype="int16", latency="high",
                        callback=lambda *a: None):
        time.sleep(1.0)                      # the stream under way first
        busy = report("streaming", listen(m, seconds))
    m.close_port()
    if idle and busy:
        print(f"spread {idle[0]:.2f} -> {busy[0]:.2f} ms, 99% {idle[1]:.2f} -> {busy[1]:.2f} ms, "
              f"missing {idle[2]} -> {busy[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
