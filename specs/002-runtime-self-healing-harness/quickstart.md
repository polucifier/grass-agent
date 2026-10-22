# Quickstart: Validating Gate 2 End to End

**Date**: 2026-10-06 | **Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md)

Runnable validation scenarios proving the harness works. Each scenario states prerequisites, the command, and the expected observable outcome tied to a spec success criterion.

Do not include implementation code here — that belongs in `tasks.md`.

## Prerequisites

### 1. Project environment

```sh
cd /home/rhea/Downloads/grass-agent-opencode
.venv/bin/python -c "import ollama, sqlite_vec; print('deps ok')"
```

Expect `deps ok`. The host interpreter (`/usr/bin/python3`) does **not** have these packages — always invoke via `.venv/bin/python`.

### 2. GRASS

```sh
grass --version
```

Expect `GRASS 8.5.0`. The harness runs the real CLI; there is no mock mode. A pre-flight failure exits `3` and names the missing dependency (FR-023, [contracts/cli.md](./contracts/cli.md)).

### 3. Local model service

```sh
ollama list
```

Expect both `qwen2.5-coder:3b` and `qwen2.5-coder:7b` plus `nomic-embed-text`. **The service is not currently running on this host** — `ollama list` reports "could not connect". Start it before any run:

```sh
ollama serve &
# wait for readiness
until ollama list >/dev/null 2>&1; do sleep 1; done
```

All inference stays local (FR-016). Nothing in the harness contacts an external service.

### 4. North Carolina dataset — **one-time, not provided by the harness**

The dataset is **absent** on a fresh host. Verified: no `nc_basic_spm*` on disk, `~/grassdata` empty, `grass-sample-data` package not installed.

```sh
mkdir -p ~/grassdata
curl -fL -o /tmp/nc.zip \
  https://grass.osgeo.org/sampledata/north_carolina/nc_basic_spm_grass7.zip
unzip -q /tmp/nc.zip -d ~/grassdata
ls ~/grassdata                     # expect: nc_basic_spm_grass8/
```

Note the `_grass7` filename: `nc_basic_spm_grass8.zip` returns **404**. The `_grass7` package loads in GRASS 8.5 (research R10).

Then apply the PERMANENT write guard **once at provisioning time** — required by Principle V and SC-002, because `--tmp-mapset` provides a writable *default mapset*, not a sandbox:

```sh
chmod -w ~/grassdata/nc_basic_spm_grass8/PERMANENT
```

This guard is a **permanent, documented property of the provisioned fixture**, not a per-run toggle. Nothing reverts it — not the harness, not teardown. That is deliberate: while the write bit is absent, no Gate 1 or Gate 2 run can mutate the dataset, and the `--tmp-mapset` workload was verified to run normally regardless. Restore it only by hand (`chmod +w`) if you deliberately need to modify the dataset outside this harness.

Verify:

```sh
grass --tmp-mapset ~/grassdata/nc_basic_spm_grass8/ \
  --exec python3 -c "from grass.tools import Tools; t=Tools(); print(t.list_grouped(type='raster')['PERMANENT'][:3])"
```

Expect a short list of NC raster names. If this prints a traceback, the dataset is not usable yet.

Confirm the dataset path, and note that `nc_spm_08_grass7` is an accepted alternative — the harness detects either.

### 5. Fixtures

```sh
ls benchmarks/fixtures/
```

Expect `points.geojson`, a `boundary.*` shapefile set, and `README.md` recording provenance, CRS (EPSG:3358, matching `nc_basic_spm_grass8`), which cases declare each fixture, and the one-time dataset provisioning steps above.

---

## Scenario A — Classifier unit check (no GRASS, no model)

Fastest confidence signal; needs no prerequisites beyond the venv.

```sh
.venv/bin/python -m pytest tests/test_classifier.py -v
```

Expected, mapping to spec criteria:

- Every verbatim GRASS string catalogued in [research.md](./research.md) §R7 maps to its intended failure mode.
- A string matching **two** content categories resolves by the mandated precedence (`missing_input` beats `schema_misuse`) — SC-005a.
- `AttributeError: Tool v_update_column (v.update.column) not found` resolves to `unknown_method`, **not** the catch-all — SC-005.
- A single-line `ToolError` with the `ERROR: ` prefix stripped still matches — the R8/D7 constraint.
- A wrapped multi-line message (7-space continuation indent) matches after normalisation.
- Classification is idempotent: same input, same output, every time — SC-005a.

## Scenario B — Executor and cleanup check (needs GRASS + dataset)

```sh
.venv/bin/python -m pytest tests/test_executor.py -v
```

Expected:

- A trivial script exits `0`.
- A script raising an exception is classified `general_exception` with a captured traceback.
- A script that deliberately segfaults is recorded as `outcome: "crashed"` with `signal_name: "SIGSEGV"` — **not** inferred from exit code 245 (research R5, decision D3).
- A script that sleeps past `--timeout` is terminated at the budget and recorded as `timeout`.
- After each of the above, the project directory contains **only** `PERMANENT` and the per-run `TMPDIR` is gone — SC-004.
- The `PERMANENT` content hash is unchanged — SC-002.

## Scenario C — Single-case smoke run (full pipeline, 3b model)

The fastest end-to-end proof. ~1 attempt × (generation + execution).

```sh
.venv/bin/python benchmarks/run_execution.py \
  --model qwen2.5-coder:3b \
  --suite benchmarks/benchmark_prompts_tier1.json \
  --max-retries 0 \
  --clean
```

Use the `-k/--case` filter to run a single case (comma-separated for several, e.g. `-k tc_01,tc_11`). A filter matching no case id exits `2` naming the unmatched ids. Expect per-case progress blocks on stdout and one report.

```sh
.venv/bin/python benchmarks/run_execution.py \
  --model qwen2.5-coder:3b --suite benchmarks/benchmark_prompts_tier1.json \
  --case tc_01 --max-retries 0 --clean
```

Expected artifacts:

```sh
ls benchmarks/output_execution/
cat benchmarks/execution_report.md
```

Confirm in `tc_01/`: `attempt_1.py`, `attempt_1.log`, `stdout`/`stderr` streams, `case_result.json`, `final.py`.

Confirm in the report: Pass@1 is stated, Pass@Healed equals Pass@1 (healing disabled), per-attempt latency and token counts appear, and the exit-status-is-not-correctness caveat is present (SC-014).

## Scenario D — Zero-shot baseline (all 40 cases, no healing)

```sh
.venv/bin/python benchmarks/run_execution.py \
  --model qwen2.5-coder:3b \
  --max-retries 0 \
  --clean
```

No `-s` flag covers both tiers — all 40 cases (SC-001). This establishes the Gate 2 Pass@1 baseline and is the comparison point for Scenario F.

Expected: every case has a recorded verdict and a retained artifact set; every failed attempt carries one of the four failure modes (SC-005).

Budget: with no healing this is one generation plus at most one execution per case.

## Scenario E — Self-healing (all 40 cases, default budget)

```sh
.venv/bin/python benchmarks/run_execution.py \
  --model qwen2.5-coder:3b \
  --max-retries 2 \
  --clean
```

Expected, beyond Scenario D's artifacts:

- Healed cases show 2–3 attempts with the repair output preserved (`attempt_2.py`, `attempt_3.py`).
- Each `case_result.json` shows `failure_mode_transitions` as an ordered list — the visible answer to "how did healing resolve it" (FR-018).
- The report states Pass@Healed above Pass@1 (SC-009) and quantifies the gain as absolute and relative difference (SC-007).

With the 7b model, expect materially longer wall-clock: a prior Gate 1 run's `ollama.log` shows ~42 s for a single 589-token generation. Use `:3b` for smoke coverage and `:7b` only for the final evaluation run.

## Scenario F — Gate 1 vs Gate 2 comparison

```sh
.venv/bin/python benchmarks/run_execution.py --model qwen2.5-coder:7b --max-retries 2 --clean
```

Open `benchmarks/execution_report.md`. Expected (FR-020, SC-013):

- Gate 1 static validity (90.0% baseline, constitution IV) beside Gate 2 Pass@1 and Pass@Healed for the same 40 cases.
- Per-mode failure counts summing to the total failed attempts (SC-005a).
- Latency and token figures per attempt ordinal, enabling cost-per-successful-case.
- The comparison labelled as two different measurement harnesses, not one continuous scale.

## Scenario G — Artifact replay (fastest full execution pass)

Uses the 40 Gate 1 scripts already in `benchmarks/output/` as attempt 1, skipping generation entirely:

```sh
.venv/bin/python benchmarks/run_execution.py \
  --reuse-artifacts --max-retries 0 --clean
```

Expected (FR-001a, SC-015):

- `case_result.json` records `attempt1_source: "reuse_artifacts"`.
- Attempt 1 token counts are `0` — no inference occurred.
- The report labels the run as replay-based so reuse figures are never read as freshly measured.

This isolates *execution* behaviour from *generation* behaviour and is the fastest way to characterise runtime failure modes across all 40 cases.

## Scenario H — Resumption

The property most likely to be silently wrong. Test it explicitly.

```sh
# start a full run, then interrupt with Ctrl-C partway through
.venv/bin/python benchmarks/run_execution.py --model qwen2.5-coder:3b --max-retries 2 --clean

# immediately re-run the same command WITHOUT --clean
.venv/bin/python benchmarks/run_execution.py --model qwen2.5-coder:3b --max-retries 2
```

Expected (FR-006a, SC-018, SC-019):

- Completed cases are skipped, not re-executed.
- The case that was interrupted mid-flight is rerun **from attempt 1** — its `attempt_1.py` is regenerated, not resumed from `attempt_2`.
- Scratch directories are absent after the interrupt (SC-004).
- The `PERMANENT` content hash matches the pre-run value (SC-002).

Then confirm the negative case — a changed configuration must invalidate prior results:

```sh
.venv/bin/python benchmarks/run_execution.py --model qwen2.5-coder:3b --max-retries 1   # budget changed
```

Expected: the resume key no longer matches, so cases rerun rather than being carried across configurations (SC-019).

## Scenario I — Report regeneration without re-execution

```sh
.venv/bin/python benchmarks/run_execution.py --report-only
```

Expected (SC-013): `benchmarks/execution_report.md` is rewritten with identical figures. No model inference, no GRASS execution — verifiable by watching that the run completes in seconds and that `ollama list` shows no new load.

## Scenario J — Pre-flight dependency failures

Each should exit `3` with a message naming the missing dependency (FR-023):

```sh
# model service down
ollama stop; .venv/bin/python benchmarks/run_execution.py --max-retries 0; echo "exit=$?"
ollama serve &

# dataset path wrong
.venv/bin/python benchmarks/run_execution.py --max-retries 0 --dataset /nonexistent; echo "exit=$?"

# unmatched case filter
.venv/bin/python benchmarks/run_execution.py -k tc_99 --max-retries 0; echo "exit=$?"
```

Expected: `exit=3` with a message naming the specific missing dependency — not a traceback, not `exit=1`. The `-k tc_99` case is an argument error and exits `2` naming the unmatched id.

`--dataset` accepts an explicit project path. Omit it and the harness auto-detects the first standard NC project under `$GISDBASE`, `$GRASSDATA`, `~/grassdata`, or `./grassdata`; when nothing is found it exits `3` naming every root it searched.

---

## Verification matrix

| Scenario | Spec criteria covered |
|---|---|
| A — Classifier | SC-005, SC-005a, FR-008, FR-008a |
| B — Executor | SC-002, SC-003, SC-004, SC-010, SC-011, SC-012, FR-003, FR-006, FR-015, FR-016 |
| C — Single case | SC-001, SC-014, SC-015, FR-019 |
| D — Zero-shot baseline | SC-001, SC-005, SC-007 |
| E — Self-healing | SC-006, SC-009, SC-017, FR-010..FR-013, FR-018 |
| F — Comparison | SC-007, SC-008, SC-013, SC-020-equivalent FR-020 |
| G — Replay | FR-001a, SC-015 |
| H — Resumption | SC-018, SC-019, FR-006a |
| I — Report-only | SC-013 |
| J — Pre-flight | FR-023, SC-016 |

## Cleanup

```sh
# verify the dataset was not mutated (SC-002)
find ~/grassdata/nc_basic_spm_grass8 -maxdepth 1 -name 'tmp_*'   # expect: no output

# remove execution artifacts for a fresh start
rm -rf benchmarks/output_execution benchmarks/execution_report.md
```