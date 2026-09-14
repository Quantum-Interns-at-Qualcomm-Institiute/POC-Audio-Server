# Bringing real optics online

This document is the contract for replacing the emulated bench with real
optical hardware. It is deliberately the deliverable of the bench-daemon
effort: everything in the `bench/` package is built so that the swap touches
**only** the three driver classes named here. Framing, clock alignment, slot
recovery, the fiber protocol, the WebSocket layer, the reservoir engine, and
the whole classical-reconciliation path ship to the real bench unchanged.

## The cut line

```
  browser  ── WebSocket ──►  bench daemon
                              ├── session.py       (frame lifecycle)
                              ├── alignment.py     ┐ recover the clock and map
                              ├── slot_recovery.py ┘ clicks to slots  ── REAL, ships as-is
                              ├── sync.py, fiber_wire.py, ws_protocol.py
                              │
                              └── drivers.py  ◄──── THE SWAP LINE ────►
                                    ├── PulseSourceDriver
                                    ├── TimeTaggerDriver
                                    └── PolarizationCompensatorDriver
                                          │
                        emulated today ───┤─── real vendor drivers tomorrow
                                          │
                              emulated_awg.py / emulated_timetagger.py /
                              pol_compensator.py  (delete or leave unused)
```

Above the line is emulator-independent. Below it, the emulated implementations
model the physics; a real bench provides concrete drivers against the same
ABCs and configures the emulated-fiber stanza off (real photons take the
fiber, so `[net] fiber_*` and `fiber_link.py` are unused on a real link).

## The three drivers (`bench/drivers.py`)

### `PulseSourceDriver` — the source bench

Prepares a frame's BB84 states and fires them. Real implementation: program
the AWG driving the polarization modulator, set the attenuator to the signal
intensity, and trigger off the mode-locked laser clock.

| Method | Contract |
|---|---|
| `configure(config)` | Apply bench parameters (rep rate, intensity). |
| `async arm(frame: TransmitFrame)` | Load a frame's prepared states. `frame.bits` and `frame.bases` are one value (0/1) per pulse slot; the daemon has already prepended the public sync string, so slot 0 is the first sync slot. |
| `async fire() -> FrameTxReport` | Emit the armed frame; return when it has left the source, with `tx_epoch_ps` in the source clock. |

The real driver **must** emit at the configured signal intensity for every
slot including the sync string (Qubit4Sync needs no intensity modulation —
this is exactly why a fixed source + static attenuator suffices). It **must
not** reorder slots or drop the sync prefix.

### `TimeTaggerDriver` — the detector bench

Reads the single-photon detectors and yields raw click timestamps. Real
implementation: wrap the vendor timetagger SDK (Swabian, PicoQuant, …).

| Member | Contract |
|---|---|
| `has_sync_input: bool` | `True` if the bench has a hardware clock reference shared with the source (`shared-clock` sync mode); `False` if synchronization must be recovered from the qubits (`qubit` mode). |
| `configure(config)` | Apply detector parameters. |
| `async start()` / `async stop()` | Acquisition lifecycle. |
| `clicks() -> AsyncIterator[Click]` | Yield detection events continuously. `Click.t_ps` is the arrival time **in the tagger's own clock** (picoseconds, no external time reference assumed); `Click.detector_id` identifies the SPAD, encoding the measured basis and bit per `DETECTOR_BASIS`/`DETECTOR_BIT` (four SPADs: Z/H, Z/V, X/D, X/A). |

Clock semantics are the crux: the driver reports times in its **local** clock,
and `alignment.py` recovers the offset and frequency relationship to the
source without any privileged knowledge — it reads only the click stream and
the public sync string. A real driver **must not** try to pre-align to the
source or annotate clicks with source-frame metadata; doing so would bypass
the recovery code that must run on the real link. (The emulator enforces this
by never letting recovery read the fiber's ground-truth frame header.)

Framing note: the emulator drives detection one fiber frame at a time
(`EmulatedTimeTagger.detect`), because the emulated fiber delimits frames
explicitly. A real timetagger yields a *continuous* stream, and the daemon
segments frames from the sync-string correlation. `session.py`'s
`DetectorBench` is the integration point to adapt when moving from batch
`detect()` to streaming `clicks()`.

### `PolarizationCompensatorDriver` — fiber polarization tracking

On a deployed fiber, polarization drifts slowly and is the dominant QBER
dynamic (as in the DTU/NBI field trial). Real implementation: motorized
polarization controllers running a coordinate-descent search that minimizes
QBER, discarding the high-QBER chunks during overshoot — which the reservoir
engine's per-frame QBER gate already does on the browser side.

| Method | Contract |
|---|---|
| `compensation_rad() -> float` | Current compensation angle applied to incoming polarization. |
| `step(observed_qber)` | Advance the search one step from the latest observed QBER. |

## Data types (`bench/drivers.py`)

- `TransmitFrame(frame_id, slots, bits, bases)` — one frame to fire. `frame_id`
  is the detector's **acquisition label** only; slot recovery never reads it.
- `FrameTxReport(frame_id, tx_epoch_ps)` — when a frame went out, source clock.
- `Click(t_ps, detector_id)` — one detection, detector clock.

## What ships unchanged

Everything above the swap line, in particular:

- **`alignment.py`** — Qubit4Sync-style offset recovery: sub-period phase from
  the click comb, then a cross-correlation of the sync-region Z-basis
  detections against the public sync string, bounded by the sync length
  (independent of payload length). Tolerates high loss.
- **`slot_recovery.py`** — maps clicks to slots under a detection gate, with a
  one-tap drift tracker that refines the period frame-over-frame.
- **`sync.py`, `fiber_wire.py`, `ws_protocol.py`, `pairing.py`, `session.py`,
  `daemon.py`** — sync string, wire formats, the pairing-authenticated
  WebSocket, and the frame lifecycle.
- The entire browser side: the reservoir engine, sifting, pooled distillation
  (error correction + verification hash + Toeplitz amplification), and the
  authenticated classical channel.

## Roadmap (named, not built)

- **Decoy states** — `config.py` reserves an `[intensities]` stanza and
  `physics.py` keeps multi-photon statistics exact under loss, so a decoy
  extension changes emission scheduling, not the physics core. Until then a
  weak-coherent source carries the photon-number-splitting residual (see the
  threat model).
- **Lower-leakage reconciliation**: the browser runs six-pass Cascade;
  parametrized Cascade (Martínez-Mateo et al.) or LDPC codes would disclose
  fewer parity bits and need fewer round trips.
- **Streaming timetagger + sync-based framing** — moving `DetectorBench` from
  batch `detect()` to the ABC's continuous `clicks()`.
- **ETSI GS QKD 014 facade** — the daemon's status/pool telemetry already
  borrows the KME vocabulary; a REST key-delivery facade would make it an
  interoperable key manager.
