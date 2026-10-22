# Phase 0 Research: Gate 2 Headless Runtime Execution & Self-Healing Harness

**Date**: 2026-10-06 | **Plan**: [plan.md](./plan.md) | **Spec**: [spec.md](./spec.md)

Every finding below was established on the actual host by executing the commands shown, or by reading the installed GRASS Python source. Findings are tagged **VERIFIED** (executed and observed) or **INFERRED** (read from source/docs).

## Environment baseline (VERIFIED)

| Fact | Value |
|---|---|
| GRASS version | 8.5.0, launcher `/usr/bin/grass`, prefix `/usr/lib64/grass85` |
| `grass --config path` | `/usr/lib64/grass85` |
| `grass --config python_path` | `/usr/lib64/grass85/etc/python` |
| Host interpreter | `/usr/bin/python3` (3.13.15). There is **no** bare `python` on this host |
| Project venv | `.venv/` with `ollama` 0.6.2, `sqlite-vec` 0.1.9, `pytest` 9.1.1 |
| Local models present | `qwen2.5-coder:3b`, `qwen2.5-coder:7b`, `nomic-embed-text` |
| Ollama service | **not currently running** — `ollama list` reports "could not connect". `~/.ollama/models/manifests/.../qwen2.5-coder/{3b,7b}` exist, so the models are installed |
| Knowledge base | `data/grass_knowledge.db`, 543 rows in `tools(name, category, description, signature, example, params_json)` |
| NC sample dataset | **absent** — see R10 |
| `GISDBASE` | unset; `~/grassdata` exists but is empty |

`python3 -c "import grass"` fails outside a GRASS session. That is expected and is the reason execution must go through a GRASS session rather than a bare interpreter.

## R1. `--tmp-mapset` semantics and PERMANENT safety

**VERIFIED** by reading `/usr/bin/grass` (`set_mapset`, lines 722–899; invoked at 2409) and by execution.

- `--tmp-mapset GISDBASE/PROJECT/` creates a **new** mapset named `tmp_<uuid4hex>` *inside an existing project*. The project must already exist; with a nonexistent path GRASS fails before doing anything: `ERROR: Location </tmp/.../NOPE> doesn't exist`, exit 1. There is no CRS fallback for `--tmp-mapset`.
- Passing the PERMANENT mapset instead of the project produces a helpful diagnostic: `<...>/nc/PERMANENT> is not a valid GRASS project because PERMANENT mapset is missing / looks like a mapset, not a project. Did you mean just </.../nc>?`
- The temp mapset sees PERMANENT maps **read-only through the normal search path**: `list_grouped(type="raster")` returned `{'tmp_...': ['tmprast'], 'PERMANENT': ['elev']}`, `find_file("elev")` resolved to `PERMANENT/cell/elev`, and `v.db.select` read a PERMANENT SQLite attribute table correctly.
- The temp mapset receives a byte-identical copy of PERMANENT's `DEFAULT_WIND` as its `WIND`, plus its own `VAR`, `sqlite/`, `.tmp/`, and `.gislock`. **PERMANENT itself is never locked** by a `--tmp-mapset` session.
- A never-opened project works: `grass -c EPSG:3358 <proj> -e` followed by `--tmp-mapset <proj>/` succeeds and leaves no trace.
- The **project directory must be writable** — `--tmp-mapset` mkdirs inside it. VERIFIED: `chmod a-w` on the project dir produces `PermissionError` at `/usr/bin/grass:887`.
- `--tmp-mapset` cannot be combined with `--tmp-project`: `ERROR: Either --tmp-project or --tmp-mapset can be used, not both`.
- Concurrency is safe: three simultaneous `--tmp-mapset` sessions each got their own uuid mapset and lock, and all cleaned up. (Gate 2 runs cases sequentially regardless.)

### Critical hazard: `--tmp-mapset` is not a sandbox

**VERIFIED**. A script inside a `--tmp-mapset` session can freely switch to PERMANENT and mutate it:

```
gs.run_command("g.mapset", mapset="PERMANENT")   => Mapset switched.  PERMANENT lock: True
tools.r_mapcalc_simple(...)                       => rasters: {'PERMANENT': ['permrast']}
```

The created raster survived the session and required manual removal. A writable *default mapset* is not isolation.

**Mitigations, both VERIFIED:**
- Dropping the write bit on the `PERMANENT` directory (`chmod -w nc/PERMANENT`): the full workload still ran with PERMANENT unchanged, and `g.mapset PERMANENT` then failed non-zero.
- A content hash of the entire `PERMANENT` tree was byte-identical (`f5290457…`) before and after both read-only and read-write workloads.

Under a read workload the hash was also unchanged, confirming ordinary reads are safe.

### Cleanup behaviour by termination signal

| Signal | Temp mapset removed? | Leftovers |
|---|---|---|
| normal exit | **yes** | none |
| Python error (exit 1) | **yes** | none |
| SIGINT | **yes** (rc `-2`) | none |
| SIGTERM | **no** (rc `-15`) | `tmp_<uuid>/` with `.gislock`, `VAR`, `WIND`; `/tmp/grass8-<user>-<pid>` |
| SIGKILL | **no** (rc `-9`) | same as SIGTERM |

Root cause: cleanup is `atexit.register(lambda: shutil.rmtree(path, ignore_errors=True))` at `/usr/bin/grass:898` plus `unlock_gisrc_mapset` at 2443. `atexit` does not run on SIGTERM/SIGKILL — no handler is installed for them (the only `signal.` use in `/usr/bin/grass` is a `SIGTERM` in `close_gui`).

**Grandchildren are not killed by GRASS.** VERIFIED: after killing only the `grass` process, the `--exec python3` child and its `sleep 300` grandchild both survived. Killing the process group cleaned them.

### Decision

Use `grass --tmp-mapset <project>/ --exec python3 …` as the primary launch (D1), and treat PERMANENT safety as a separate concern: `chmod -w` the PERMANENT directory at bootstrap plus a content-hash assertion before and after every run (D5). Perform a post-run sweep of stray `tmp_*` mapsets and the per-run `TMPDIR` (D6).

## R2. Interpreter and `import grass.tools`

**VERIFIED**. `--exec` is handed to `Popen(batch_job, shell=False, env=os.environ)` at `/usr/bin/grass:1393`, so the plain `python3` found on `PATH` runs — **not** `GRASS_PYTHON`. The child printed `PY: /usr/bin/python3`.

`import grass.tools` succeeds in that plain `python3` because GRASS injects the path, not because the interpreter is special. Observed child environment:

```
PYTHONPATH=/usr/lib64/grass85/etc/python
GISBASE=/usr/lib64/grass85
GISRC=/tmp/grass8-<user>-<pid>/gisrc
GIS_LOCK=<pid>
GRASS_PYTHON=/usr/bin/python3
TMPDIR=/tmp/grass8-<user>-<pid>
PATH=/usr/lib64/grass85/scripts:/usr/lib64/grass85/bin:...
grass.tools file: /usr/lib64/grass85/etc/python/grass/tools/__init__.py
```

`GRASS_PYTHON` only overrides the interpreter name for `wxgui.py`. VERIFIED: `GRASS_PYTHON=/usr/bin/python3 grass … --exec python …` → `ERROR: Execution of <python …> failed: [Errno 2] No such file or directory: 'python'`.

`grass --exec script.py` relying on a shebang also works — `/usr/bin/grass:1396-1399` falls back to `[sys.executable] + batch_job` on `ENOENT`. Extra arguments after the script path pass through untouched.

**Verified minimal invocation:**

```sh
grass --tmp-mapset /abs/path/to/gisdb/nc_basic_spm_grass8/ --exec python3 /abs/path/script.py
```

with the script containing simply `from grass.tools import Tools` / `import grass.script as gs`. Observed: `session mapset: tmp_036f4df0… | Tools ok: True`.

### Decision

Resolve `grass --config path` and `grass --config python_path` at runtime rather than hard-coding `/usr/lib64/grass85` (D2), and invoke plain `python3`. Never invoke bare `python`.

## R3. `--tmp-project` as an alternative sandbox

**VERIFIED**: `GISDBASE` becomes `$TMPDIR/grass8-<major>-<user>-<pid>`, the project is hardcoded `tmpproject`, the mapset `PERMANENT`. `TMPDIR` is honored (VERIFIED: `TMPDIR=/my/dir` relocated the session), which makes containment easy. CRS from `--tmp-project EPSG:3358` is identical to a real NC project (`g.proj -p`: NAD83(HARN)/North Carolina, LCC, lat_0=33.75, lon_0=-79, x_0=609601.22, meters, SRID EPSG:3358). Everything vanishes at normal exit; SIGKILL still leaks `/tmp/grass8-<user>-<pid>`.

**Tradeoff**: it creates a *new empty project under a different GISDBASE*, so the NC dataset is invisible and every layer would need re-importing per run. That defeats the purpose of using NC as a read-only fixture.

**Decision**: `--tmp-mapset` is the execution mode. `--tmp-project` is rejected for this feature (D1) but noted as the cleaner choice for CRS/region-only work with no data dependency.

## R4. `grass.script.setup.init()` fallback

**VERIFIED** signature (`/usr/lib64/grass85/etc/python/grass/script/setup.py:287`):

```python
init(path, location=None, mapset=None, *, grass_path=None, env=None,
     lock=False, timeout=0, force_unlock=False) -> SessionHandle
```

- There is no `gisdb` argument; `path` *is* the gisdbase. `mapset` without `location` raises `ValueError` from `resolve_mapset_path`.
- **`init()` has no temp-mapset support.** It does not create mapsets; it validates and writes a gisrc via `NamedTemporaryFile(delete=False)`, removed by `finish()`.
- It writes to `GISRC` outside the mapset. VERIFIED: PERMANENT listing and content hash unchanged across `init`/`finish` with `lock=True`.
- **`lock=True` creates `.gislock` inside the mapset you point at** and removes it on `finish()`. Pointing it at PERMANENT therefore creates and deletes a lock file *inside PERMANENT*. Use `lock=False` against PERMANENT for a zero-write guarantee.
- `finish()` runs `clean_default_db` (SQLite VACUUM above `MEMORYMB`) and `clean_temp` (`etc/clean_temp`) against the current mapset. VERIFIED: a planted `PERMANENT/.tmp/fake_old` survived, so unrelated files are not purged — but the operation does act on the current mapset, so it must not be run against PERMANENT.
- Manual temp-mapset creation through `init()` is possible but awkward. VERIFIED working sequence: `init(gisdb, location=…, mapset="PERMANENT")` → `g.mapset -c mapset=tmp_<uuid>` → **manually `os.remove()` the `.gislock` that `g.mapset -c` leaves behind** (else the next `init(lock=True)` raises `MapsetLockingException`) → `init(..., mapset=tmp_<uuid>, lock=True)` → work → `shutil.rmtree`. PERMANENT unchanged throughout.
- Ordering constraint: `import grass.script` must work *before* `init()`, so the fallback script must do `sys.path.insert(0, <python_path>)` itself.

**Decision**: retained only as the fallback the user's decision 1 specifies — "only if the CLI wrapper is unsupported on the host environment". The pre-flight check probes `grass --tmp-mapset` support once per run; if unsupported, the fallback worker runs `init()` against a temp mapset it created itself, with the `.gislock` removal handled explicitly.

## R5. Crash detection and exit-code conventions

**VERIFIED** exit-code matrix for `grass --exec`:

| Child outcome | `grass --exec` rc | Correct inference |
|---|---|---|
| success | 0 | — |
| `sys.exit(5)` | 5 | exit 5 |
| `sys.exit(245)` | **245** | exit 245, **not** SIGSEGV |
| SIGSEGV (`ctypes.string_at(0)`) | **245** | SIGSEGV |
| SIGABRT (`os.abort()`) | 250 | SIGABRT |
| self-SIGKILL | 247 | SIGKILL |
| uncaught Python exception | 1 | Python error |
| SIGINT to `grass` itself | `-2` | SIGINT (grass got the signal) |
| SIGTERM / SIGKILL to `grass` itself | `-15` / `-9` | grass was signalled |

The mechanism is `proc.wait()` at `/usr/bin/grass:1397` then `sys.exit(returncode)` at 2460; Python maps `sys.exit(-11)` to status **245**. So **`returncode < 0` is unreachable through `grass --exec`**, and the `256 - rc` heuristic is unsafe because `exit(245)` and SIGSEGV are byte-identical.

### Verified fix — forked inner status reporter

A small wrapper forks, `execv`s the real script, and lets the surviving parent `waitpid()` and record `WIFSIGNALED`/`WTERMSIG` into a JSON file. Observed driver output:

```
[ok    ] child={'grass_returncode': 0, 'child': {'returncode': 0,  'status': 'exited'}}
[fail  ] child={'grass_returncode': 3, 'child': {'returncode': 3,  'status': 'exited', 'exit_code': 3}}
[crash ] child={'grass_returncode': 245,'child': {'returncode': -11,'status': 'crashed', 'signal_name': 'SIGSEGV'}}
```

**Decision** (D3): the harness ships `grass_agent/inner_wrapper.py`, copied into the scratch directory and placed between `--exec` and the generated script. Crash classification reads the status file, never the exit code.

Notes: `faulthandler.register(11, …)` does **not** work — VERIFIED `RuntimeError: signal 11 cannot be registered, use enable() instead`. `faulthandler.enable()` gives a traceback but no programmatic signal number.

One consequence worth recording: a segfault inside a GRASS *module* invoked via `grass.script.run_command` is caught by `grass.script` and converted to `CalledModuleError` — a script segfaulting after `run_command` gave `grass` rc 1, not 245. Module-level crashes therefore surface as ordinary non-zero exits. Given Gate 2 forbids `run_command` in generated code this is largely moot, but it means "hard crash" detection is best-effort for crashes *inside* modules rather than inside the Python layer.

## R6. Timeouts, process groups, and dangling artifacts

**VERIFIED trap**: `Popen.kill()` / `subprocess.run(timeout=…)` kills only the `grass` wrapper, leaving the Python grandchild orphaned, and `communicate()` then blocks until that grandchild exits — measured **60.1 s elapsed for a 60 s child against a 3 s budget**. Killing only the `grass` process left both the Python child and its `sleep 9999` grandchild running.

**Verified pattern:**

```python
p = subprocess.Popen(cmd, stdout=PIPE, stderr=PIPE, text=True,
                     start_new_session=True, env=env)
try:
    out, err = p.communicate(timeout=budget)
except subprocess.TimeoutExpired:
    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
    try:
        out, err = p.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        out, err = p.communicate()
```

`start_new_session=True` gives the child its own process group; before the kill the group was `[['59663','59663'],['59671','59663'],['59675','59663']]` (grass, python, sleep) and after `[]`. With `killpg` the timeout returned in 3.0 s with `rc=-9` and no orphans.

**`grass --timeout N` is a mapset *lock acquisition* timeout, not an execution timeout.** VERIFIED: `--timeout 2` on an 8-second job completed normally with exit 0. The user's `--timeout` budget is therefore enforced by the harness (D4) and is never passed to `grass --timeout`.

**Post-kill artifacts**: a SIGKILLed session leaves a stale `.gislock`. A subsequent `grass` run recovered automatically because the recorded PID was dead, but the leaked directory still has to be swept. The leaked lock is always inside the temp mapset, never in PERMANENT, so it cannot block future sessions.

**Decision**: sweep = pre-run snapshot of `<project>/tmp_*`, post-run set difference filtered by run start time, `shutil.rmtree` each; plus removal of the per-run `TMPDIR` (D6).

## R7. Failure classification — observed GRASS 8.5 signatures

All strings below were produced by running real GRASS commands. Message routing: **stdout** carries only results (map names, `r.info` reports, `v.db.select` rows); **stderr** carries `ERROR:`, `WARNING:`, usage dumps, and progress. Note `g.findfile` prints to stdout even on failure.

### 1 — Missing Input Map or Layer (VERIFIED, all stderr)

```
ERROR: Raster map <nonexistent> not found
ERROR: Vector map <nonexistent> not found
ERROR: Vector map <nosuchmap> not found in current mapset
ERROR: Vector map <nosuchmap> not found in the current mapset. Unable to
       modify vector maps from different mapsets.
ERROR: Database connection not defined for layer <1>
WARNING: Table <nope> not found in database <$GISDBASE/.../sqlite.db> using driver
         <sqlite>
ERROR: Mapset <nosuchmapset> does not exist
ERROR: Space time raster dataset <nope@PERMANENT> not found
ERROR: Unable to read input from <no_such_file.txt>
ERROR: Unable to open input file <no_such_file.txt>: No such file or
       directory
ERROR: Unable to open datasource <no_such.tif>
ERROR 4: /tmp/.../no.tif: No such file or directory        <- GDAL, no "ERROR: " prefix
```

Reproduced with `r.info`, `r.univar -g`, `r.stats -n`, `r.pack`, `r.out.ascii`, `g.region raster=…`, `r.slope.aspect elevation=…`, `v.info`, `v.db.select`, `v.db.connect`, `v.to.db`, `g.list type=raster mapset=…`, `t.rast.list`, `r.in.ascii`, `v.in.ascii`, `r.in.gdal`, `r.external`.

Note the missing-table case is a **`WARNING:`, not `ERROR:`**, with rc=1. Do not anchor this category on `ERROR:`.

### 2 — Schema / Parameter Misuse (VERIFIED, all stderr)

Missing required option — two formats, the colon variant followed by a tab-indented description:
```
ERROR: Required parameter <map> not set:
	(Name of raster map)
ERROR: Required parameter <input> not set:
	(Name of input vector map)
```
Also a **no-colon** variant: `ERROR: Required parameter <column> not set` (`v.what.rast`).

Unknown/invalid option — three distinct formats:
```
ERROR: r.info: Sorry, <bogus> is not a valid parameter
ERROR: r.mapcalc: Sorry, <output> is not a valid parameter
ERROR: Sorry<extra1> is not a valid option          <- positional args; no module prefix
```

Value out of range, output-exists, mutually-exclusive options, and `r.mapcalc` parse failure:
```
ERROR: Value <update> out of range for parameter <option>
	Legal range: cat,area,compact,fd,perimeter,length,count,coor,start,end,sides,query,slope,sinuous,azimuth,bbox
ERROR: option <slope>: <dem> exists. To overwrite, use the --overwrite flag
ERROR: Select a buffer distance/minordistance/angle or column, but not
       both.
syntax error
Parse error
ERROR: parse error
Invalid map <missingmap>       <- the ONLY reliable missing-input signal for r.mapcalc
Parse error
ERROR: parse error
```

**High-value LLM trap**: `r.mapcalc(expression="…", output="x")` is *always* a parameter error — `r.mapcalc` has no `output` option, only `[expression] [region] [file] [seed] [nprocs]`.

**Partial-name matching**: GRASS accepts unambiguous option prefixes, so `r.info m=dem f=json`, `v.db.select m=pts c=cat`, `v.buffer in=pts out=bb distance=10` all succeed. A slightly-wrong option name from the model often *works*, so this category is systematically under-counted.

### 3 — Non-existent Attribute or Method (VERIFIED, source + runtime)

`Tools.__getattr__` **does** intercept (`session_tools.py:605-616`) and delegates to `ToolFunctionResolver.get_tool_name(..., exception_type=AttributeError)` (`support.py:148-182`), raising a plain `builtins.AttributeError`. Resolution order: `name.replace("_", ".")` → `shutil.which(tool_name)` → membership in `gs.get_commands()` → fuzzy suggestions.

Two message forms:
```
AttributeError: Tool v_update_column (v.update.column) not found (but found v_db_addcolumn)
AttributeError: Tool r_mapcalc_ (r.mapcalc.) not found (but found r3_mapcalc, r_mapcalc)
AttributeError: Tool or attribute foobar_baz_qux (foobar.baz.qux) not found (check session setup and documentation for tool and attribute names)
AttributeError: Tool or attribute r_slope (r.slope) not found (check session setup and documentation for tool and attribute names)
```

**The `'Tools' object has no attribute 'x'` wording in the user's decision 3 never appears on this install.** The plan must pattern for `Tool .* not found` / `Tool or attribute .* not found`. Recorded here because the user input used the non-occurring phrasing.

Python 3.13 appends `Did you mean: 'v_db_addcolumn'?` to the *traceback rendering* (PEP 678) but not to `str(e)` — VERIFIED `e.args == ('Tool v_update_column (v.update.column) not found (but found v_db_addcolumn)',)`.

Related, also this category:
```
OSError: Cannot find the executable r.nonexistenttool      <- tools.run("r.nope", ...)
TypeError: ToolFunctionResolver.get_function.<locals>.wrapper() takes 0 positional arguments but 1 was given
AttributeError: module grass.tools has no attribute Nope
```

**No `TypeError` for a wrong keyword on a known tool.** `Tools` methods accept `**kwargs` and forward to `make_command` (`core.py:291`), so a bogus keyword becomes an extra module argument and either succeeds or becomes category 2.

### 4 — General Python / Runtime

```
ModuleNotFoundError: No module named 'nonexistent_module_xyz'
SyntaxError: invalid syntax
ToolError: Output of r.info cannot be parsed as JSON. Did you use format="json"?
ValueError: No text output for <tool> to be parsed as JSON
```
plus `KeyError`, `ZeroDivisionError`, `IndexError`, and — per FR-022 — timeouts and hard crashes.

## R8. `grass.tools` error propagation (VERIFIED by source read)

`Tools.call_cmd` (`session_tools.py:544-603`) runs `gs.Popen(command, stdout=PIPE, stderr=PIPE)`, builds a `ToolResult` carrying `returncode`/`stdout`/`stderr`, and on non-zero calls `gs.handle_errors(..., exception=ToolError, stderr=stderr)`. `handle_errors` (`core.py:448-470`) defaults to handler `"raise"` → `raise exception(module, code, returncode=..., errors=stderr)`.

So **`grass.tools` wraps rather than propagates**. The type is `grass.tools.session_tools.ToolError`, MRO: `ToolError → grass.exceptions.CalledModuleError → subprocess.CalledProcessError → SubprocessError → Exception`. Not `SystemExit`, not a bare `CalledProcessError`.

`ToolError.msg` has two shapes:

*Single-line stderr* — errors first, with `ERROR: ` **stripped**:
```
Raster map <nonexistent> not found
Run `r.slope.aspect elevation=nonexistent slope=s1` ended with an error (return code 1)
```

*Multi-line stderr* — run details first, then the full raw stderr including `ERROR: `:
```
Run `r.info` ended with an error (return code 1):
Outputs basic information about a raster map.

Usage:
 r.info [-grseh] map=name [format=name] ...
ERROR: Required parameter <map> not set:
	(Name of raster map)
```

Attributes: `.returncode` (int, negative for signals), `.errors` (raw stderr), `.cmd`, `.tool`, `.msg`.

### Consequence for classification

The literal token `ERROR: ` is **absent from the uncaught traceback** for single-line failures. Every category-1 and category-2 pattern must match the bare body. This is the single most important classification design constraint (D7).

Also VERIFIED: `Tools(capture_output=True)` — the default — swallows the module's streams into the exception. `.errors` holds the untouched stderr including the `ERROR: ` prefix, so it is available to the classifier. `capture_output=False` lets raw stderr reach the parent's stderr.

## R9. Precedence ordering — the deliberate deviation

The user's decision 3 and FR-008a fix the content precedence as: missing input → schema/parameter → missing method → general. Applied naively as a match order, that would file every `AttributeError` into the general catch-all, because `AttributeError: Tool v_update_column (v.update.column) not found` matches none of the category-1/2 patterns and falls through.

**Resolution (D8)**: test the missing-method signatures **first**, then apply the specified precedence to the remaining content categories. This is collision-free — VERIFIED that `ToolError` strings never contain the phrase `Tool <x> … not found` — and it preserves the mandated precedence over every case where two content categories actually compete.

Recorded overlap behaviour, all VERIFIED:

1. **Schema error masks a missing map.** `r.info map=nonexistent bogus=1` emits *only* `Sorry, <bogus> is not a valid parameter` — the option parser runs before the map lookup and aborts. Category 1 is therefore systematically **under**-reported when the model invents an option name at the same time. Correct per precedence (2 is what was reported), but a real reporting caveat.
2. Same masking for `v.db.select map=nosuchmap table=nosuchtbl format=csv` → only the `table` error; and `v.to.db map=nosuchmap option=cat columns=id format=csv` → only `Value <csv> out of range for parameter <format>`.
3. **The reverse overlap, which precedence exists for**: `v.db.select map=pts table=nosuchtable` reports `Sorry, <table> is not a valid parameter` even though a table is missing. Where a call genuinely emits both a map-not-found and an invalid-parameter message, missing-input wins.
4. **`r.mapcalc` ambiguity**: both a bad expression and a missing map produce identical trailing `Parse error / ERROR: parse error`. Only the `Invalid map <x>` line distinguishes them, so that pattern must be evaluated before the `Parse error` patterns.
5. **`ERROR 4:` (GDAL)** has no `ERROR: ` prefix and no "not found" wording — needs its own alternative or it falls to category 4.
6. **Line wrapping**: GRASS hard-wraps at ~72 chars with a 7-space continuation indent, splitting mid-sentence. Normalise `re.sub(r"(?m)^[ \t]+", " ", combined)` before matching.
7. **Localisation**: VERIFIED `LANG=de_DE.UTF-8` turns `ERROR: Raster map <nope> not found` into German and `LANGUAGE=en` does **not** override it. Force a fixed English locale on all children (D9).
8. **Wrong-type values misfile**: `tools.r_info(map=["a","b"])` becomes `map=a,b` and lands in category 1 as `Raster map <a,b> not found`. Unavoidable at the string level; flagged if the rate looks suspicious.

## R10. Dataset availability on this host

**VERIFIED absent.** No `nc_basic_spm*` anywhere on disk; `~/grassdata` empty; `/usr/lib64/grass85` is the real prefix (not `/usr/lib/grass85`); `rpm -qa | grep -i grass` shows only `grass-8.5.0-1.1` and `grass-doc-8.5.0-1.1` — **`grass-sample-data` is not installed**; no bundled geofile (the only `.tif`s are PROJ geoid grids; no `.shp` under the GRASS prefix).

It must be fetched. `nc_basic_spm_grass8.zip` returns **404**. `nc_basic_spm_grass7.zip` (50 MB, `Content-Length 50937243`) is the live URL and loads in 8.5 despite the `_grass7` name; `nc_spm_08_grass7.zip` (159 MB) is the full dataset.

Offline NC-equivalent, VERIFIED: `grass -c EPSG:3358 <path> -e` produces the identical CRS (`g.proj -p` matches `--tmp-project EPSG:3358` exactly). But it yields an **empty** project. `r.in.nc` is **not available** on this host (VERIFIED ENOENT), so there is no NetCDF-based offline construction path. Real NC layers require the download.

**Decision (D10)**: dataset bootstrap is a documented, explicitly-flagged prerequisite, not something the harness silently fabricates. `benchmarks/fixtures/README.md` records provenance. A pre-flight check named in FR-023 exits non-zero with a clear message when the dataset is absent, and the quickstart documents the one-time fetch. Per FR-016 the harness itself makes no network calls — the fetch is a human setup step performed outside the tool, consistent with the offline mandate applying to *inference and evaluation*, not to one-time environment provisioning.

## R11. Token accounting for FR-018 / SC-008

`OllamaProvider.chat` (`llm_provider.py:13-15`) returns only `response.message.content`, discarding the counters. The Ollama response object also carries `prompt_eval_count` and `eval_count` — VERIFIED present in the response for the version installed, though the service was not running during this check and a live confirmation is a Gate 2 task.

**Decision (D11)**: add `OllamaProvider.chat_with_stats(messages) -> (text, stats)` alongside the existing `chat`, leaving `chat` untouched so `code_generator.py:118` keeps working. Where the counters are absent or zero, the run summary records zero rather than estimating — per SC-015, `--reuse-artifacts` attempt 1 also reports zero tokens because no inference occurred.

## R12. Ollama service state

VERIFIED: the local service is **not running** (`could not connect to ollama server, run 'ollama serve' to start it`), though `ollama.log` shows a prior successful run and both model tags are installed. The harness must therefore treat a reachable model service as a hard pre-flight dependency per FR-023, failing fast with a named dependency rather than per-case.

## R13. Independent confirmation of D3, D4, D6

The three decisions that carry the most design risk were re-verified end to end on a throwaway project (`grass -c EPSG:3358 /tmp/opencode/ptest/ncproj -e`), using the minimal inner wrapper from R5.

| Scenario | `grass --exec` rc | `status.json` | Temp mapset left behind |
|---|---|---|---|
| `ok.py` — normal run | `0` | `{"returncode": 0, "status": "exited", "exit_code": 0}` | no |
| `seg.py` — `ctypes.string_at(0)` | **`245`** | `{"returncode": -11, "status": "crashed", "signal": 11, "signal_name": "SIGSEGV"}` | no |
| `ok.py` again, via wrapper | `0` | `{"returncode": 0, "status": "exited", "exit_code": 0}` | no |
| `hang.py` — `time.sleep(300)`, killed | `124` | absent — wrapper never got to write | **yes** — `tmp_6e42393423aa4e18abdfe602f17e69d2` |

**Confirmed:**
- **D3 is necessary and sufficient.** A segfault surfaced as `245` through the wrapper while `status.json` unambiguously recorded `SIGSEGV`. Crash classification cannot rely on the exit code.
- **D4 is necessary.** The hang left the wrapper with no chance to write its status file; a hang is detectable only from the harness side, via `communicate(timeout=)` plus `killpg`.
- **D6 is necessary.** The killed run leaked `tmp_<uuid>/`, exactly as R1 predicted. A post-run sweep is not defensive padding — without it, repeated runs accumulate temp mapsets in the project directory and SC-004 fails.

The scratch area `/tmp/opencode/ptest` and stray `/tmp/grass8-*` directories were removed afterwards; nothing in the repository was modified.

## Resolved-unknown summary

| Item | Resolution |
|---|---|
| Interpreter for `--exec` | plain `python3`; GRASS injects `PYTHONPATH` (D2) |
| Crash detection | forked inner wrapper writes a status JSON (D3) |
| Timeout enforcement | harness-side `communicate(timeout=)` + `killpg` (D4) |
| PERMANENT immutability | `chmod -w` guard + content hash + post-run sweep (D5, D6) |
| Classification anchoring | bare message body, never `ERROR:` (D7) |
| Precedence deviation | missing-method signatures tested first, collision-free (D8) |
| Locale | fixed English locale + indentation normalisation (D9) |
| Dataset | absent; documented one-time prerequisite (D10) |
| Token accounting | additive `chat_with_stats` (D11) |
| CLI-unsupported fallback | `init()` worker with explicit `.gislock` removal (R4) |

No `NEEDS CLARIFICATION` markers remain in the Technical Context.