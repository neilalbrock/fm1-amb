# The USB audio input: what was measured, the stems, what's next

AMB-1's USB audio input (`firmware/src/usb.c`, `FELUCCA_UAC`) sends the master to a computer as
16-bit stereo at 44.1 kHz, so the FM-1 can be recorded over the cable. This page keeps what was found
on a real FM-1 when the input grew to ten channels, the master and the four layers apart.

## What the FM-1's USB can carry

The packet-size probe (`EN_UAC_CH=N ./build.sh`, `tools/uac_probe.py`) declares N channels and fills
all but the master with a counter, so a packet lost, repeated, cut short or shifted shows on the
computer. Three minutes each into macOS, 15 October 2026:

| Channels | Packet | Serviced every 0.5 ms | Every 0.1 ms (`EN_UAC_TICK=1`) |
|---|---|---|---|
| 6 | 540 B | clean | |
| 8 | 720 B | blocks of stale frames, in bursts | clean |
| 10 | 900 B | | clean |
| 11 | 990 B (the full-speed most) | | clean |

At 8 channels and up a packet takes about half the 1 ms frame to send, and `uac_service` only looked
every 0.5 ms whether the last had gone; when the timer and the USB clock drifted into a bad phase, the
next packet missed its frame and macOS read its 0.25 s input buffer before the data came (the stale
frames were always 11,025 frames old). Looking every timer tick puts the next packet out in time.

## The stems (`EN_STEMS=1 ./build.sh`)

Ten channels: 1-2 the master, 3-4 the pad, 5-6 the bells, 7-8 the bass (mono, on both), 9-10 the pulse.
The layers are dry: the echo and the plate are shared by all four, so only the master has them. The
stems follow the MASTER knob, like the master, and sum to its dry part (before its soft clip).

- `amb.c`: each layer renders into its own buffer (`LAYER_L/R`) and the mix is their sum;
  `en_render_stems` hands them out as 16-bit. Without `EN_STEMS` the engine is as it was, sample for
  sample.
- `usb.c`: the ring and the resampler carry frames of 10 channels (`ua_frame_t`); the ring is 1024
  frames rather than 2048 (20 KB, as RAM allows); the stream is serviced every tick.
- Tests: `amb-stems` (each layer on its pair, the bass the same on both sides, the sum against the
  master), `uac-stems` (ten channels through mismatched clocks and render times up to 5.5 ms).

On the FM-1, 15 October 2026: two minutes recorded clean (`tools/uac_stems.py`: the bass pair the same
in every frame, no frame repeated; the FM-1's own count of short packets, dropped frames and late ones
at 0). The audio load 35 % with the stream idle, 50 % while recording. Both were read off the Setup
page then; it shows neither now. RAM 77,784 of 98,304 bytes with the screen reader in.

### USB MIDI beside it

`tools/midi_clock_probe.py` times the FM-1's MIDI clock with the audio stream idle and then while all
ten channels are recorded (60 s each, 72 bpm):

| | Idle | Streaming |
|---|---|---|
| Spread | 0.79 ms | 0.85 ms |
| 99 % within | 5.67 ms | 5.70 ms |
| Worst | 5.86 ms | 5.89 ms |
| Missing ticks | 0 | 0 |

No change worth the name. The ~5.8 ms worst case is the instrument's own in both: a tick is made on
its sample in the render but sent after the render's half. The isochronous packets take about 60 % of
each frame and the MIDI's bulk packets fit beside them; a hub shared with other full-speed gear has
less to spare.

## Next

1. The resampler's cost: the stream adds about 15 points of CPU. The cubic's four weights depend only
   on the position, so they can be worked out once per output frame and shared by the ten channels
   (four multiply-adds each instead of the whole polynomial), and the history could be indexed rather
   than shifted. Measure the audio load before and after (`en_dbg.cpu_q8` in `main_fm1.c`; the Setup
   page no longer shows it, so a temporary readout or a debug read).
2. Channel names: hosts show channels 3-10 by number. UAC1's input terminal can point at string
   descriptors (`iChannelNames`) for "Pad L", "Pad R" and the rest.
3. Whether the stems should be the normal build: about 25 KB of RAM and the CPU above, and a recorder
   sees ten inputs where it saw two. Until then they stay a build option.
4. The hardware run above was of the stems build before the screen reader came in; run
   `tools/uac_stems.py` and `tools/midi_clock_probe.py` again on the build with both.
5. A space pair: the echo and plate's return on its own would make the stems sum to the whole master,
   but needs an eleventh and twelfth channel, past what a full-speed packet carries at 16 bits; it
   would have to replace the master.
