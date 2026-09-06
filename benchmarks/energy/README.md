# Embedding energy harness

W0-2 repairs the float32 equivalence gate and makes carbon inputs explicit.
The automated fixtures exercise arithmetic and failure paths; they do **not**
measure device energy or establish an energy improvement.

## Run

Run from an interactive macOS terminal, after supplying your sourced protocol
and carbon factors. These environment variables intentionally have no example
carbon values:

```sh
benchmarks/energy/run.sh \
  --duration-seconds "$ENERGY_PHASE_SECONDS" \
  --repetitions "$ENERGY_REPETITIONS" \
  --carbon-intensity "$ENERGY_INTENSITY_G_PER_KWH" \
  --embodied "$ENERGY_EMBODIED_G_PER_SECOND"
```

`--carbon-intensity` and `--embodied` are mandatory, finite and nonnegative.
The runner validates them, and the protocol, before any `sudo` or model import.
`--validate-only` performs just that validation. `--batch-size` defaults to the
batch from the review's W3-2 probe; `--sample-rate-ms` defaults to the system
powermetrics manual's sampling interval. Both are configurable experimental
protocol choices. Choose phases long enough to contain sensor samples.

`run.sh` owns sensor authorization and cleanup; it replaces the duplicate
AppleScript sensor launcher previously embedded in Python. Only powermetrics
runs elevated. `ENERGY_PYTHON` can select a Python interpreter; otherwise the
runner uses the repository's `.venv/bin/python`. The Python entry point can use
an already running stream via `--external-power-file`; without it, it directs
the operator to `run.sh`. An unavailable neural model is an explicit error.
The harness does not change the model's cache location.

## Units and equivalence

`I = --carbon-intensity` is the electricity region's intensity in gCO2eq/kWh.
`--embodied` is an **already allocated emission rate** in gCO2eq/s, not the total
device footprint. Derive it from sourced lifecycle emissions divided by expected
life in seconds, multiplied by the resource share reserved for this workload.
Record the region, observation period, lifecycle assessment, expected lifetime
and reservation assumptions alongside your run. The harness records input
values and units but does not verify their provenance.

For each measured phase, with `t` its actual elapsed seconds and `N` its actual
model input token count:

```text
M_phase [gCO2eq] = embodied_rate [gCO2eq/s] * t [s]
O_phase [gCO2eq] = (energy_j / 3600000) [kWh] * I [gCO2eq/kWh]
carbon per 1000 tokens = (O_phase + M_phase) * 1000 / N
joules per 1000 tokens = energy_j * 1000 / N
```

The model's `tokenize` method supplies `attention_mask`; summing it counts
non-padding tokens after truncation, including special tokens. The harness
reconstructs every completed input batch and counts tokens **after all timed
phases**. It never estimates tokens from characters. Scalar and batch phases
use the same deterministic text generator; their LRU cache is cleared before
each phase so the probe cannot warm scalar inputs into cache hits.

Equivalence decodes `encode`/`encode_batch` blobs using
`np.frombuffer(blob, dtype=np.float32)`. Empty, malformed, nonfinite, mismatched
outputs and errors above `np.finfo(np.float32).eps` are refused before phases.
The tolerance is absolute (`rtol=0`) and deliberately strict. NumPy supplies its
floating-point definition; this is **not** a universal bound on model inference
error. The probe validates the selected batch, device and run only. A fixture
at `0.5` and its next float32 value toward `1` demonstrates why comparing byte
values was incorrect.

## Measurement boundary and artifacts

`raw_system_energy_j` covers the sensor's combined **CPU+GPU+ANE** estimate.
It is neither wall-plug energy nor a complete device/application SCI score.
Memory, storage, screen, power supply losses, model warm-up and token counting
are excluded. Carbon uses raw energy; idle-subtracted energy is a separate
diagnostic and retains negative values so idle noise remains visible.

The phase energy estimate is mean sampled watts multiplied by elapsed seconds;
samples are assigned by their end timestamps. Finite sampling introduces phase
boundary error. CPU-only samples are refused. An incomplete final sample may
be ignored only when its timestamp is after every measured phase, with an
explicit warning; malformed samples inside phases are refused.

Successful runs preserve `results.json`, `MANIFEST.json` (commit and source
hashes) and the exact analyzed `powermetrics.txt` snapshot under
`benchmarks/results/energy/`. The snapshot is taken while the external sensor
is running. On failure, the shell reports the retained raw temporary file;
it never stores a model there. Sensor stop failures return nonzero and do not
wait indefinitely for a sensor that could not be signalled.

Stopping sends `SIGINT` directly to the existing sudo parent, which relays it
to powermetrics under macOS's normal sudoers/PAM process model. This requires
no new sudo invocation, so an expired authentication ticket does not prevent
cleanup. A nonstandard sudo policy that replaces its parent with the root
command may deny the signal; the runner then reports failure without waiting.

## Primary sources

- [Green Software Foundation SCI specification](https://sci.greensoftware.foundation/):
  operational emissions `O=E*I`, embodied allocation `M=TE*TS*RS`, functional units.
- [NumPy frombuffer](https://numpy.org/doc/stable/reference/generated/numpy.frombuffer.html),
  [finfo](https://numpy.org/doc/stable/reference/generated/numpy.finfo.html), and
  [allclose](https://numpy.org/doc/stable/reference/generated/numpy.allclose.html):
  byte interpretation, machine epsilon and explicit tolerance semantics.
- [SentenceTransformer.tokenize](https://www.sbert.net/docs/package_reference/sentence_transformer/SentenceTransformer.html#sentence_transformers.SentenceTransformer.tokenize)
  and [Hugging Face tokenizer attention masks](https://huggingface.co/docs/transformers/main_classes/tokenizer):
  actual model preprocessing and non-padding token masks.
- [NIST SP 811 chapter 4](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-4-two-classes-si-units-and-si-prefixes)
  and [chapter 5](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-5-units-outside-si):
  watt/joule, kilo/milli prefixes and seconds per hour.
- Local macOS `powermetrics(1)`, `/usr/share/man/man1/powermetrics.1`, consulted
  2026-09-06: sample-rate default, continuous sampling, flushing and stop signals.
- Local macOS `sudo(8)` 1.9.17p2, `/usr/share/man/man8/sudo.8`, sections
  "Process model" and "Signal handling", and [Apple kill(2)](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/kill.2.html):
  user-generated signal relay and real/effective UID permission checks.
- Protocol/acceptance: `tasks/codex-green-remediation-plan.md`, W0-2 and W3-2.

## Fixture verification

```sh
.venv/bin/pytest tests_py/benchmarks/test_energy_*.py
.venv/bin/ruff check benchmarks/energy tests_py/benchmarks/test_energy_*.py
.venv/bin/ruff format --check benchmarks/energy tests_py/benchmarks/test_energy_*.py
```

The shell tests use a fake sudo executable for validation and a simulated
sensor under a PTY for successful and failing workload cleanup. No test starts
powermetrics, invokes real sudo or downloads/loads model weights.
