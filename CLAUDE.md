# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

AMB-1 is replacement firmware for the M-VAVE FM-1 (JieLi AC79, pi32v2 CPU): a generative ambient
instrument after Eno's *Music for Airports*. The same C sources also run on a computer as a scripted
simulator, in the browser as an emulator, and (the engine alone) as a web app. See README.md,
BUILDING.md, docs/MANUAL.md (the user manual) and LICENSING.md (what came from Felucca / X0X / FoMni).

## Commands

```
tests/run_tests.sh                 # everything that runs without a device; logs in build/host/*.log
sh host/build_host.sh              # the simulator alone -> build/host/amb_host
build/host/amb_host tests/scenarios/first.amb build/scenarios/first   # one scenario: WAV, PNGs, checks
./build.sh                         # firmware -> build/amb.bin, build/loader/ota.bin, build/amb.fwsc
./build.sh --release X.Y           # release package build/amb-X.Y.fwsc (identity FM-1_7XXYYZZ)
EN_STEMS=1 ./build.sh              # 10-channel USB audio: master + dry layers (BUILDING.md has the options)
python3 tools/fm1_install.py build/amb.fwsc      # install over USB MIDI (mido, python-rtmidi)
sh web/emu/build.sh                # browser emulator -> build/emu (needs emcc)
sh web/app/build.sh                # engine-only web app -> build/app (needs emcc)
```

Running a single unit test: copy its line from `tests/run_tests.sh`, e.g.
`cc -O2 -ffp-contract=off -std=c99 -Wall -Wextra -Wdouble-promotion -Werror -DEN_HOST -Ifirmware/src/dsp -o build/host/amb_test tests/host/amb_test.c firmware/src/dsp/amb.c && build/host/amb_test`.

- The firmware build needs the JieLi toolchain (`tools/get_toolchain.sh`), the AC79 SDK checkout
  (`AC79_SDK`, default `~/fw-AC79_AIoT_SDK`), Pillow, and on macOS Docker (each tool runs in a
  `linux/amd64` container). Host tests need only `cc`; the emu/app tests run only if `emcc` is on
  PATH; the update-path tests need `build/amb.fwsc` (and `AC79_SDK` for the loader test).
- `tools/build.py` fails the build if any soft-double routine is linked (a `double` crept in) and
  checks image, RAM and `.pool` sizes.
- Publishing: `tools/publish_pages.sh X.Y` (GitHub Pages site via `tools/make_pages.py`, force-pushes
  `gh-pages`); `web/app/publish.sh` (copies build/app into a sibling `charles.pizza` checkout, commits
  and pushes). Both push to remotes; don't run them unasked. `web/make_site.py` is Felucca's original
  site script, not AMB-1's.

## Architecture

**The instrument** is `firmware/src/dsp/amb.c` + `amb.h` (read amb.h's header comment first: layers
PAD / BELLS / BASS / PULSE, the arc, the echo/tape/plate chain). Threading contract: `en_render()` runs
in the audio interrupt; everything else calls `en_set` / `en_pool` / `en_play` / ... which post
commands the render drains at the start of a block. The `volatile en_*` globals are written by the
render and only read by the UI. No allocation, no libm, float only: maths comes from `fastmath.h`.
Parameters are the `P_*` enum with ranges/texts in `en_param_info()` / `en_param_text()`; the eight
pieces are recipes in `en_piece()`.

**Bit-exact host = device.** The AC79 FPU is single precision with no fused multiply-add, so every
build (device, host, wasm) uses `-ffp-contract=off`, and host tests use `-Wdouble-promotion -Werror`.
Keep it that way: no `double`, no libm calls in firmware code, float literals with `f`.

**The app** (`firmware/src/app/`) is written against `plat.h`, the whole hardware interface (time,
buttons/keys/encoders by panel label, LEDs, USB MIDI, storage objects, CPU load).
- `project.c`: `project_t` (everything saved, `PROJ_MAGIC` / `PROJ_FORMAT` in `app.h`) — the playing
  piece plus a `slot_t` per piece. Changing the saved layout means bumping `PROJ_FORMAT` and handling
  migration in `project_load` (see `tests/scenarios/migrate.amb` and the host's `storev3` command).
- `ui.c`: pages, controls, screen drawing (via `gfx.c` over `lcd_fill` / `lcd_blit`).
- Device implementation: `plat_fm1.c`, `panel.c`, `main_fm1.c` (boot, audio ISR, main loop).

**Unity builds.** The device app is one compilation unit, `firmware/src/main.c`, which `#include`s the
HAL headers, `libc.c`, `lcd.c`, `gfx.c`, `usb.c`, `storage.c`, `ota.c`, then the app `.c` files in a
fixed order (order matters). Only `dsp/amb.c` is a separate unit (built at `-O2`; the rest at `-Os`).
The host simulator `host/amb_host.c` likewise `#include`s `gfx.c`, `project.c` and `ui.c` and supplies
its own `plat.h` implementation; `web/emu/amb_web.c` `#include`s `amb_host.c` again for wasm.
`web/app/amb_api.c` exposes only the engine (no UI) to an AudioWorklet. `-DEN_HOST` selects host
code paths; `-DEN_WEB` the emulator's.

**Scenario tests** (`tests/scenarios/*.amb`) drive the whole app through `amb_host`: `wait`, `tap`,
`press`, `turn`, `key`, `midi`, `wav`, `shot`, `reboot`, and `expect WHAT VALUE` (exact, `<N` or `>N`;
exits 1 on mismatch). The command list is at the top of `host/amb_host.c`; new `expect` keys are added
in its `strcmp(what, ...)` chain. Outputs land in `build/scenarios/<name>/`. The screenshots in
`docs/img/screen-*.png` are simulator screenshots, checked in by hand (no script copies them);
`tools/gen_manual_figures.py` draws the panel SVG around one of them.

**USB audio input** (`usb.c`, `FELUCCA_UAC`): the audio ISR resamples each rendered block (cubic,
steered by the ring's fill) into a ring of frames (`ua_frame_t`, `UAC_RCH` channels: 2, or 10 with
`EN_STEMS`, where `amb.c` renders each layer into its own buffer via `LAYER_L/R`); `uac_service`, from
the TIMER5 ISR and nested in the render, queues one 1 ms isochronous packet at a time on EP4. Packets
of 8+ channels take ~0.5 ms on the wire, so they need servicing every tick (`EN_UAC_TICK`), not every
fifth. Default builds must stay bit-identical to the stereo path; `uac_test.c` simulates mismatched
clocks and render jitter.

**Platform layer** (`firmware/hal/`, `firmware/loader/`, `usb.c`, `storage.c`, `ota.c`, `tools/`
packaging/install/rescue, `web/fm1*.js`) is inherited from Felucca via X0X and keeps the web installer
and update path working; change it with care, and the update-path tests (`ota-entry`, `update-loader`,
`installer`) cover it.

## Conventions

- Every source file starts with `SPDX-License-Identifier: GPL-3.0-only`.
- Comments, docs and commit messages are plain descriptive prose about what the instrument does
  (e.g. "The echo evolves in stereo: with Motion its two heads wander across the field, ..."), no
  conventional-commit prefixes. Match that voice.
