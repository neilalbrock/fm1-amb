/* SPDX-License-Identifier: GPL-3.0-only */
/* The USB audio input (usb.c, FELUCCA_UAC) against clocks that do not agree: the FM-1's I2S asks for a
 * 256-frame half every 5.8 ms at RATE_IN, and the render hands it to the ring a varying time later
 * (0.3 to 5.5 ms: a light render, a busy bar), while the host takes a 1 ms packet of the 44.1 pattern
 * by its own clock. A sine goes into every channel, each at its own pitch; after 20 s of settling each
 * must come out at its pitch by the host's clock (the resampler took up the difference), clean, with no
 * packet short of frames, no frame dropped for want of room, and the ring's low point near UA_MID.
 * X0X's I2S runs at ~44,145..44,180 Hz.
 *   -DFELUCCA_UAC_STEMS=1 -DFELUCCA_UAC_CH=10: the master and the four layers' pairs (EN_STEMS)
 *   -DFELUCCA_UAC_CH=N (4..11): the packet-size probe's layout */
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#define RING_PUBLISH() __asm__ volatile("" ::: "memory")
#define FELUCCA_UAC 1
static void fm1_delay_ms(uint32_t ms) { (void)ms; }
#include "usb.c"

#define SECS 30
#define SETTLE 20
#define HALF 256u
static int16_t outs[UAC_RCH][44100 * SECS];

static double pitch(uint32_t c) { return 1000.0 + 150.0 * c; }

static uint32_t rng = 1;
static double urand(void)
{
    rng = rng * 1664525u + 1013904223u;
    return (rng >> 8) * (1.0 / 16777216.0);
}

static int run(double rate_in)
{
    static int32_t blk[2 * HALF];
    static int16_t st[HALF * (UAC_RCH - 2u) + 1u];
    double t_half = 0, t_tap = -1, t_out = 0, ph[UAC_RCH] = {0};
    long nout = 0, a = 44100L * SETTLE, i;
    uint32_t under_settled = 0, fill_max = 0, c;
    int ok = 1;
    memset(&uac, 0, sizeof uac);
    memset(&usb, 0, sizeof usb);
    ua_w = ua_r = 0;
    usb.config = 1;
    uac.alt = 1;
    uac.flowing = 1;
    uac.fill_lo = 0xFFFFFFFFu;
    while (t_out < SECS) {
        if (t_out <= t_half && (t_tap < 0 || t_out <= t_tap)) {     /* the host's 1 ms frame */
            ua_frame_t d[UA_MAXF];
            uint32_t n, u = uac.underruns, k;
            n = uac_packet(d);
            if (t_out > 10.0 && uac.underruns != u)
                under_settled++;
            for (k = 0; k < n && nout < 44100L * SECS; k++, nout++)
                for (c = 0; c < UAC_RCH; c++)
                    outs[c][nout] = (int16_t)d[k].s[c];
            t_out += 0.001;
        } else if (t_tap >= 0 && t_tap < t_half) {                     /* the render hands its block in */
            uac_tap(blk, st, HALF);
            if (ua_w - ua_r > fill_max && t_out > 1.0)
                fill_max = ua_w - ua_r;
            t_tap = -1;
        } else {                                                        /* the I2S asks for a half */
            uint32_t k;
            uac_render_start();
            for (k = 0; k < HALF; k++)
                for (c = 0; c < UAC_RCH; c++) {
                    double s = sin(2 * M_PI * ph[c]) * 0.5;
                    if (c < 2)
                        blk[2 * k + c] = (int32_t)(s * 8388607.0) & ~0xFF;
                    else
                        st[(UAC_RCH - 2u) * k + c - 2u] = (int16_t)(s * 32767.0);
                    ph[c] += pitch(c) / rate_in;
                }
            t_tap = t_half + (0.3 + 5.2 * urand()) * 1e-3;
            t_half += HALF / rate_in;
        }
    }
    for (c = 0; c < UAC_RCH; c++) {
        const int16_t *o = outs[c];
        double err = 0, sig = 0, f, w, t0 = -1, t1 = 0;
        long zc = 0;
        for (i = a + 1; i < nout; i++)                   /* the pitch: rising crossings, placed between samples */
            if (o[i - 1] < 0 && o[i] >= 0) {
                t1 = i - 1 + (double)-o[i - 1] / (o[i] - o[i - 1]);
                if (t0 < 0)
                    t0 = t1;
                else
                    zc++;
            }
        f = zc / ((t1 - t0) / 44100.0);
        w = 2 * M_PI * f / 44100.0;
        for (i = a + 2; i < nout; i++) {                 /* a sine's next sample from the two before */
            double pred = 2 * cos(w) * o[i - 1] - o[i - 2];
            err += (o[i] - pred) * (o[i] - pred);
            sig += (double)o[i] * o[i];
        }
        if (fabs(f / pitch(c) - 1.0) >= 5e-5 || 10 * log10(err / sig) >= -70.0) {   /* 50 ppm: under a cent */
            printf("    channel %u: %.3f Hz (%.0f in), residual %.1f dB\n", c + 1, f, pitch(c), 10 * log10(err / sig));
            ok = 0;
        }
    }
    printf("  in %.0f Hz, %u ch: %u short packets after 10 s, %u dropped, low point %u (UA_MID %d), fill at most "
           "%u of %u\n", rate_in, UAC_RCH, under_settled, uac.overruns, uac.fill_min, UA_MID, fill_max, UA_N);
    return ok && under_settled == 0 && uac.overruns == 0 && uac.fill_min > UA_MID / 2u && uac.fill_min < 2u * UA_MID &&
           fill_max + UA_MAXF < UA_N;
}

#if FELUCCA_UAC_CH > UAC_RCH
/* the packet-size probe: packets of N channels, the master in 1-2, frame << 4 | c in the others,
 * counting on across packets (tools/uac_probe.py reads them so) */
static int probe(void)
{
    ua_frame_t fr[UA_MAXF];
    uint32_t n, i, c, p, bytes, frames = 0, bad = 0;
    uint16_t pk[UA_MAXF * FELUCCA_UAC_CH];
    for (i = 0; i < UA_MAXF; i++) {
        fr[i].s[0] = (uint16_t)i;                       /* L = i, R = 0xBEEF */
        fr[i].s[1] = 0xBEEF;
    }
    for (p = 0; p < 300; p++) {
        n = 44u + (p % 10u == 9u);
        bytes = uac_spread((uint32_t *)pk, fr, n);
        bad += bytes != n * FELUCCA_UAC_CH * 2u || bytes > UAC_MAXP;
        for (i = 0; i < n; i++, frames++) {
            const uint16_t *s = pk + i * FELUCCA_UAC_CH;
            bad += s[0] != i || s[1] != 0xBEEF;
            for (c = 2; c < FELUCCA_UAC_CH; c++)
                bad += s[c] != (uint16_t)((frames & 0xFFFu) << 4 | c);
        }
    }
    printf("  probe: %d channels, packets of %u bytes at most, %u frames, %u wrong\n", FELUCCA_UAC_CH,
           UAC_MAXP, frames, bad);
    return bad == 0;
}
#endif

int main(void)
{
#if FELUCCA_UAC_CH > UAC_RCH
    int ok = probe();
#else
    int ok = run(44145.0) & run(44100.0) & run(44300.0);
#endif
    printf(ok ? "uac: ok\n" : "uac: FAILED\n");
    return !ok;
}
