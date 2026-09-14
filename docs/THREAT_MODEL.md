# BB84 QKD Threat Model

## System Model

The system consists of three parties and two communication channels:

- **Alice** (sender): Prepares and sends quantum states encoding key bits
- **Bob** (receiver): Measures incoming quantum states to extract key bits
- **Eve** (eavesdropper): Adversary attempting to learn the key

**Quantum channel**: Fiber-optic link carrying single photons. Untrusted — Eve has full access.

**Classical channel**: A WebRTC DataChannel (DTLS-encrypted transport) carrying basis reconciliation, error correction, and privacy amplification. BB84's security proof requires this channel to be *authenticated* — Eve may read but must not be able to modify or inject messages. **This implementation authenticates it in two tiers**:

1. **Link-keyed MAC** (`channel-auth.js`): both sides derive per-direction HMAC keys (HKDF-SHA-256) from the invite link's capability token. Every *protocol* message travels as `{v, seq, payload, tag}` with a monotonic per-direction sequence (fresh per round, so a failed round cannot leave the sides in divergent sequence states), so modification, injection, replay, reordering, and dropping all fail verification. The `control` channel — the source's `session-restart` announcement — is authenticated on its own MAC domain, so a forged restart fails verification and is dropped. The one channel left unauthenticated is `quantum`, the loopback path's per-frame detection sets, bounded instead by the sift/index bounds-checks that make hostile detections fail the session cleanly rather than corrupt key material (a lifetime MAC sequence on that per-frame hot path would desync on legitimate session churn, so authentication there would cost more than it buys against an attacker who must already have broken DTLS). The DTLS certificate fingerprints from the SDP are cross-checked over the authenticated channel before the first round. **Scope, stated plainly: the signaling server mints the room token and therefore always holds it.** This tier defends against *network* MITMs who do not hold the token; it defends against the signaling server not at all. The SAS below is the only defense against a malicious or compromised signaling server.
2. **SAS display**: a short authentication string (6 digits + 4 emoji), derived purely from the two DTLS certificate fingerprints, is shown under the video on both sides with a "compare on camera" prompt and a mismatch button that tears the call down. It is a pure function — identical on both sides by construction, stable across rounds and reconnects — so an honest channel can never drift into a false mismatch. Comparing it defeats an attacker who holds the invite token (the signaling server included): a MITM terminating DTLS presents its own fingerprints, and the two sides' strings visibly differ.

The honest statement of what this buys: **authenticated if your invite-link channel was; verified if you compared the SAS.** A compromised link channel *plus* users who never compare the SAS remains MITM-able — that residual is fundamental to any scheme bootstrapped from a shared link. Beneath the MAC layer, every classical message is additionally type-checked with strict positional sequencing and bounds-checked payloads, and both sides independently enforce the QBER threshold.

**Integrity-failure semantics**: a failed MAC, sequence violation, or fingerprint disagreement is *either* tampering *or* an ordinary fault (a dropped message, a version skew across a deploy). One event is not proof of an attacker, and a false "man-in-the-middle!" alarm on every network blip teaches users to ignore the real one. The implementation therefore treats an integrity failure as a failed round: it retries like any other failure, and only persistent failure (three consecutive) latches the session — permanent red "channel integrity lost" state, no further rounds until the user leaves and rejoins. Media meanwhile continues under the last good key (the worker never downgrades to plaintext); what is lost is the ability to re-key, and the pill says so.

## What BB84 Protects Against

### Intercept-Resend Attacks

Eve intercepts each photon, measures it in a randomly chosen basis, and re-sends a new photon based on her measurement result. When Eve's basis matches Alice's, she learns the correct bit and re-sends it faithfully. When her basis doesn't match (50% of the time), she gets a random result and re-sends in the wrong state.

**Detection**: When Bob measures these re-sent photons in Alice's original basis, the bits Eve corrupted produce errors ~25% of the time. The QBER rises to approximately 25% under full intercept-resend, well above the 11% threshold.

### Individual Attacks

Eve performs independent operations on each qubit. The BB84 security proof shows that for any individual attack, the mutual information between Eve and the final key can be bounded by the QBER. Privacy amplification removes Eve's information when QBER < 11%.

**Implementation**: privacy amplification is a seeded Toeplitz hash (leftover hashing) over GF(2). Alice draws a fresh `n + m − 1`-bit seed per round from the platform CSPRNG (`crypto.getRandomValues`), transmits it over the classical channel (the seed is public — security comes from its freshness and uniformity, not its secrecy), and both sides compress the `n` corrected bits to the same `m = 128`-bit key. Every parity bit the source discloses during Cascade, and the verification hash, is subtracted from the extractable-key budget. The source stops answering parity queries once the budget is spent, so a mint whose budget cannot cover the 128-bit target aborts (`budget`) instead of emitting a weakened key.

### Collective and Coherent Attacks

More powerful attacks where Eve entangles a probe with each qubit and performs a joint measurement later. The Shor-Preskill proof (2000) establishes that BB84 is secure against all attacks (including coherent attacks) when QBER < 11%, provided error correction and privacy amplification are performed correctly.

## Photon Number Splitting (PNS) Attacks

Our source uses attenuated coherent light (weak coherent pulses), not true single photons. The photon number per pulse follows a Poisson distribution with mean μ ≈ 0.1. This means:

- ~90.5% of pulses contain 0 photons (empty)
- ~9.0% contain exactly 1 photon (secure)
- ~0.5% contain 2+ photons (vulnerable to PNS)

In a PNS attack, Eve splits off one photon from multi-photon pulses and stores it in a quantum memory. After basis reconciliation, she measures her stored photons in the correct basis, learning those key bits without introducing any errors.

**Mitigation**: The low μ (0.1) minimizes multi-photon probability. The decoy-state protocol (not implemented in this simulation) would provide full protection by allowing Alice and Bob to estimate the single-photon transmission rate independently.

**Current status**: Our simulation models Poisson statistics faithfully. PNS attacks are a known limitation documented here for transparency.

## QBER Threshold Derivation

The 11% threshold comes from the information-theoretic security bound for BB84 with one-way error correction:

The key rate r per sifted bit is:
```
r = 1 - 2·h(QBER)
```

where h(p) = -p·log₂(p) - (1-p)·log₂(1-p) is the binary entropy function.

Setting r = 0 gives the maximum tolerable QBER:
```
1 - 2·h(QBER_max) = 0
h(QBER_max) = 0.5
QBER_max ≈ 0.11 (11%)
```

Above 11%, privacy amplification cannot guarantee that Eve has negligible information about the final key.

## System Assumptions

1. **Trusted devices**: Alice's source and Bob's detectors are not compromised. There is no detector blinding, Trojan horse attacks on the source, or other device-level attacks. (Device-independent QKD would relax this assumption but is not implemented.)

2. **Authenticated classical channel**: implemented in two tiers (link-keyed MAC + SAS, see the System Model above). The residual assumption is that either the invite link traveled over a channel the attacker cannot read *and* the attacker is not the signaling server (which always holds the token it minted), or the users compare the SAS on camera. With neither, a MITM on the classical channel breaks the protocol regardless of quantum security.

3. **No side channels**: The implementation does not leak key material through timing, power consumption, electromagnetic emissions, or other side channels.

4. **Random number generation**: key bits, basis choices, and the Toeplitz seed are drawn from the platform CSPRNG (`crypto.getRandomValues`). The simulated channel's physics (photon loss, wrong-basis measurement outcomes) deliberately uses a plain PRNG — it models nature, not secrets.

## Known Limitations

1. **Simulation, or emulated optics — not a real quantum link.** By default the quantum channel is simulated in the browser. An optional hardware-bench mode (`OPTICAL` badge) runs a Python daemon per bench, but its instruments are *emulated* (`bench/`); the code above the driver ABCs is the code a real bench would run, and `docs/HARDWARE.md` is the swap contract. Neither mode provides physical security until real single-photon hardware is behind the drivers — the badge says `SIMULATED` or `OPTICAL (emulated)` and never claims otherwise.

2. **No decoy states**: neither the browser simulator nor the emulated bench implements the decoy-state protocol (Lo, Ma, Chen 2005), required for security with weak-coherent sources against PNS attacks. The emulated physics keeps multi-photon statistics exact under loss and `config.py` reserves an `[intensities]` stanza, so a decoy extension changes emission scheduling rather than the physics core — but until it exists, the PNS residual stands (see the PNS section).

3. **Cascade error correction, correctness-checked, not leakage-optimal**: distillation runs Cascade (Brassard & Salvail 1993) over the pool: six passes, the first block size set from the pool's QBER (k₁ ≈ 0.73/QBER, at least 16 blocks per pass) and doubling each pass up to half the pool, passes after the first over shared random permutations, with bisection to each erroneous bit and back-correction of earlier passes. In simulation it leaks about 1.2 × n·h(QBER) parity bits at 5–11% QBER, and about two mints in a thousand keep an error pair that no pass separates. Those are caught before privacy amplification by a truncated key-verification hash (the ε_cor-correctness step of Tomamichel–Lim–Gisin–Renner), which discards the pool and fails the mint rather than minting divergent keys. Cascade is interactive (a few round trips per pass); lower-leakage, less interactive reconciliation (parametrized Cascade, LDPC codes) remains future work.

4. **Finite-key effects, quantified.** The extractable key length obeys ℓ ≤ n·(q − h(Q_tol + µ)) − leak_EC with a finite-statistics penalty µ ≈ √(ln(1/ε_sec) / k), where k is the number of QBER sample bits (Tomamichel–Lim–Gisin–Renner, Nat. Commun. 3, 634). At the demo's per-frame sample sizes (k ≈ 10²) and ε_sec = 10⁻¹⁰, µ ≈ 0.5 — larger than any tolerable QBER, so the demo pools yield **formally zero** composably-secure key. The reservoir is demo-grade *by construction*; a `finite_key_strict` operating point (pool ≈ 2×10⁵ sifted bits, k ≳ 10⁴, minutes per key — the block size the DTU field trial chose) is the honest slow mode, named but not the default.

5. **Time-varying channel, partially modeled**: the emulated bench models slow polarization drift on the fiber (the dominant QBER dynamic on a real deployed link) with a coordinate-descent compensator; the browser simulator still uses fixed loss/noise. Full time-varying loss and non-polarization noise remain future work.

## Attack Surface

This table describes what the code actually does — every mitigation listed here
is implemented and tested, and the residual risks are stated rather than
papered over.

| Component | Risk | Mitigation (implemented) | Residual risk |
|-----------|------|--------------------------|---------------|
| Signaling: connect/create/join | Flooding, room squatting | Per-IP token bucket (30/min default, `QVC_RATE_LIMIT`); connections over the cap are refused; bucket table swept on a timer and hard-capped; `X-Forwarded-For` is ignored unless `QVC_TRUSTED_PROXIES` is set (then only the hop a trusted proxy vouched for is used) | In-memory, per-process; resets on restart. Behind a proxy the limit is only as good as `QVC_TRUSTED_PROXIES` being set correctly — unset, all clients behind one proxy share a bucket |
| Room access | Uninvited joiners | Room ids are ~128-bit `secrets.token_urlsafe` capability tokens carried in the invite link's URL fragment; join errors don't echo tokens; dashboards/logs only ever see redacted prefixes | Anyone holding the link can join — the link is the credential; share it over a channel you trust |
| `/admin/*` endpoints | Recon (rooms, sids), unauthorized ops | Fail-closed shared secret (`QVC_ADMIN_SECRET`, constant-time compare); rejections are shape-identical to a framework 404, wrong-secret probes are rate-limited and logged; responses and server logs redact sids and room ids regardless | Secret distribution is out of band |
| Media frames | Plaintext leak before/without a key | Fail-closed crypto worker: frames are **dropped** (never passed through) when no key is installed, on short/malformed frames, and on GCM auth failure; the decrypt side keeps a two-key ring selected by the frame header so a re-key doesn't freeze the video; a mid-call renegotiation offer is ignored rather than rebuilding a keyless worker; browsers without `RTCRtpScriptTransform` get a red "unsupported" pill and no key is ever installed; the UI pill shows worker-reported state (amber/green/red) | A user can read the red pill and choose to keep waiting; no media flows either way. On an unsupported browser the call cannot be encrypted at all — the honest outcome is no media |
| Key material in memory | Memory dump | Keys live only in the crypto worker as non-extractable WebCrypto `CryptoKey`s; the reservoir mints and rotates keys continuously on a ~10 s floor (`ROTATION_FLOOR_MS`), the KID incrementing per mint, with a small key ring | Rotation is event-driven, not a hard wall-clock guarantee. The BB84 secret is never used as the AES key directly — each epoch derives a key + salt via HKDF-SHA-256 |
| Frame framing | Nonce reuse, header tampering, cross-epoch confusion | **SFrame-aligned** (RFC 9605): per-frame nonce = epoch salt XOR a monotonic **counter** (retires the random-IV birthday bound at the source, not by rotation cadence); the header (KID + CTR + keyframe bit) is bound as AES-GCM **AAD**, so tampering it fails the tag; the KID selects the epoch from the 2-entry ring, so a re-key never freezes the video. `crypto.js` is the shared, unit-tested implementation the worker uses in production | Header bit-packing is a simplified variant of the RFC's (both ends are ours); MLS (RFC 9420) group rekeying is deliberately not used — overkill for two parties, which already share a fresh secret per mint |
| Classical channel | MITM, injection | Link-keyed HMAC envelope with per-direction sequence numbers (tamper/replay/inject ⇒ latched `auth-failure`) over both the `classical` frame/mint traffic and the `control` session-restart channel; DTLS fingerprints cross-checked over the authenticated channel; SAS display for on-camera verification (a ~40-bit string, adequate only because the commit-then-reveal fingerprint exchange reduces an active MITM to one blind guess — RFC 6189); typed + sequenced message layer beneath; both-side QBER enforcement; mux drops malformed JSON/unknown channels and caps buffers | Compromised invite link + no SAS comparison = MITM-able (stated above). The `quantum` detection channel is unauthenticated but bounds-checked (see System Model) |
| Eavesdropper toggle | Misread as a real attack control | It is a **local demo control**: the room creator's client injects intercept-resend into its own *simulated* quantum channel so viewers can watch the QBER spike. It is not an admin feature and grants nothing over a real channel | None — it only degrades the toggler's own session |
| Third-party script | Supply-chain (CDN) | socket.io-client is vendored into the repo and pinned with a Subresource Integrity `integrity` hash (a tampered copy is refused, not executed); no runtime third-party script loads | Vendored copy and its SRI hash must be bumped together for security releases |
| Page content injection | XSS, exfiltration | No XSS sink exists (peer/user values reach the DOM only via `textContent` / `escapeAttr`); a Content-Security-Policy (`<meta>`) additionally pins `script-src`/`style-src`/`connect-src`, blocks plugins/objects, and forbids cleartext exfil, bounding any future sink | CSP keeps `'unsafe-inline'` for script (the UI's inline `on*` handlers) until an `addEventListener` refactor; `frame-ancestors` must be set as an HTTP header at deploy (it is ignored in `<meta>`) |
| Configuration | Parameter tampering | Environment variables are local-only; CORS origins are exact strings or fully anchored regexes (prefix-attack origins like `localhostevil.com` are rejected, with regression tests); legacy port-wildcard entries are translated to anchored regexes at startup with a warning | — |
| Deploy skew | A cached `app.js` driving a new worker (or vice versa) across a deploy | Script tags carry a `?v=` cache-busting query bumped per release, so both files roll over together | Users mid-call during a deploy keep the old pair until reload |
| Browser↔bench daemon (optical mode) | A web page or local process slurping raw detections, or driving the attack control | The daemon binds loopback only (refuses a non-loopback bind without `insecure_bind`), checks the browser `Origin` against an allowlist, and requires a one-time pairing token (printed to the daemon's stdout, `secrets.token_urlsafe`, constant-time compare) on the first message; unpaired connections are dropped, and only one pairing is active at a time; the browser holds the pasted token in `sessionStorage` (per-tab, cleared on close) rather than persisting it at rest in `localStorage` | A same-user local attacker who can read the daemon's stdout gets the token — same trust class as the invite link. The WS carries raw sifted material, so the loopback bind is load-bearing |
| Emulated fiber (optical mode) | Reading the "photons" off the daemon-to-daemon link | The link carries pulse records with cleartext bit values **by construction** — it is the emulation of a physical fiber, not a secure channel — and is confined to loopback/LAN. The pluggable Eve tap on it is a *modeled attacker* for the demo, not a vulnerability | On a real bench this link does not exist (photons take the fiber); the emulator's cleartext records must never leave the lab network |
| Mode badge honesty | A user trusting `OPTICAL` as a security claim | The badge reports the negotiated backend only: `SIMULATED`, or `OPTICAL (emulated)` while the instruments are emulated. It never asserts physical security, and optical mode engages only when both peers present complementary benches — otherwise both fall back to the simulator with a visible notice | The badge tracks the backend, not the presence of *real* single-photon hardware; that distinction lives in this document and `docs/HARDWARE.md` |
| Channel-auth tier (roadmap) | Forging the classical MAC | The link-keyed envelope MAC is HKDF-HMAC — **computationally** secure. The QKD-standard construction is information-theoretic Wegman–Carter with key recycling (composable per Portmann) | Not yet implemented. The roadmap: once the reservoir mints keys, recycle a slice as the ITS authentication key for later frames — the classic QKD bootstrap. Explicitly out of scope today |

**Historical note — `key.bin`**: earlier revisions of this repository wrote a
`key.bin` file from a prototype key-persistence experiment. It was never used
to protect live traffic, the code path is gone, and the filename remains in
`.gitignore` only to keep stray copies out of version control. Treat any
`key.bin` found in old checkouts as dead material: delete it; do not reuse it.

## References

1. Bennett, C. H., & Brassard, G. (1984). "Quantum cryptography: Public key distribution and coin tossing." Proceedings of IEEE International Conference on Computers, Systems and Signal Processing.
2. Shor, P. W., & Preskill, J. (2000). "Simple proof of security of the BB84 quantum key distribution protocol." Physical Review Letters, 85(2), 441.
3. Lo, H. K., Ma, X., & Chen, K. (2005). "Decoy state quantum key distribution." Physical Review Letters, 94(23), 230504.
4. Brassard, G., & Salvail, L. (1993). "Secret-key reconciliation by public discussion." Advances in Cryptology — EUROCRYPT '93.
