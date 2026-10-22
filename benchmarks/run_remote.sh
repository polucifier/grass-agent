#!/usr/bin/env bash
set -e

# Gate 2 remote provisioning. Installs everything the headless execution
# harness and its GRASS/dataset-gated tests need on a stock Colab VM:
#   Ollama + models, GRASS GIS, the North Carolina sample dataset, Python deps.
#
# Run from the repository root:
#   bash benchmarks/run_remote.sh          # run the test suite (default)
#   bash benchmarks/run_remote.sh eval     # run the Gate 1 evaluation instead

# ---------------------------------------------------------------------------
# 1. System packages
# ---------------------------------------------------------------------------
# zstd must be present first: the Ollama installer refuses to extract its
# tarball without it, and stock Colab images do not ship it. curl/unzip are
# needed for the dataset; software-properties-common for add-apt-repository.
apt-get update -qq
apt-get install -y -qq zstd curl unzip software-properties-common locales

# The executor pins LANG/LC_ALL to en_US.UTF-8 so GRASS errors stay in English
# and the classifier's patterns keep matching. Generating the locale prevents
# glibc from emitting a setlocale warning into every child's captured stderr.
locale-gen en_US.UTF-8

# ---------------------------------------------------------------------------
# 2. GRASS GIS (grass-core)
# ---------------------------------------------------------------------------
# Ubuntu 24.04's stock grass-core is 8.3.2, and the UbuntuGIS stable PPA caps
# out at 8.4.2 on noble. Both predate `grass.tools` -- the Tool API the harness
# requires (FR-015) and which only exists from GRASS 8.5 onward (experimental in
# 8.5, stable in 8.6). The UbuntuGIS PPA is added for shared geospatial library
# dependencies; the `bleedingedge/noble-bleed` PPA supplies grass-core 8.5.0.
add-apt-repository -y ppa:ubuntugis/ubuntugis-unstable
add-apt-repository -y ppa:bleedingedge/noble-bleed
apt-get update -qq
apt-get install -y -qq grass-core

# ---------------------------------------------------------------------------
# 3. Unprivileged operator account
# ---------------------------------------------------------------------------
# Colab runs as root, but the PERMANENT write-guard tests (SC-002) assert with
# os.access(..., W_OK), which is always true for root regardless of the mode
# bits -- and root can chmod its way past the guard anyway. The suite is meant
# to run as an ordinary user, so create one and run the tests as that user.
GRADER=grader
id -u "$GRADER" >/dev/null 2>&1 || useradd -m -s /bin/bash "$GRADER"
GRADER_HOME="$(getent passwd "$GRADER" | cut -d: -f6)"

# ---------------------------------------------------------------------------
# 4. Ollama and the local models
# ---------------------------------------------------------------------------
curl -fsSL https://ollama.com/install.sh | sh
nohup ollama serve > /tmp/ollama.log 2>&1 &
sleep 8

ollama pull qwen2.5-coder:7b
ollama pull nomic-embed-text

# ---------------------------------------------------------------------------
# 5. North Carolina sample dataset (one-time prerequisite)
# ---------------------------------------------------------------------------
# The `_grass8` archive 404s; nc_basic_spm_grass7.zip is the live package and
# loads in GRASS 8.4/8.5 despite the name. ~50 MB.
mkdir -p "$GRADER_HOME/grassdata"
if [ ! -d "$GRADER_HOME/grassdata/nc_basic_spm_grass7/PERMANENT" ]; then
  curl -fL -o /tmp/nc_basic_spm_grass7.zip \
    https://grass.osgeo.org/sampledata/north_carolina/nc_basic_spm_grass7.zip
  unzip -q -o /tmp/nc_basic_spm_grass7.zip -d "$GRADER_HOME/grassdata"
fi
chown -R "$GRADER:$GRADER" "$GRADER_HOME/grassdata"
ls -d "$GRADER_HOME/grassdata/nc_basic_spm_grass7/PERMANENT"

# The PERMANENT write guard is a permanent property of the fixture (SC-002).
# `grass --tmp-mapset` is NOT a sandbox: a script calling `g.mapset PERMANENT`
# can write there and survive the session. Drop the write bit so the harness's
# zero-mutation assertion is meaningful. Verification reads the mode bits, not
# `test -w`, because the latter is meaningless for root.
PERMANENT="$GRADER_HOME/grassdata/nc_basic_spm_grass7/PERMANENT"
chmod -w "$PERMANENT"
python3 - "$PERMANENT" <<'EOF'
import os, sys
if os.stat(sys.argv[1]).st_mode & 0o222:
    sys.exit("PERMANENT write guard is still set; refusing to run")
EOF

# Fail fast if the installed GRASS cannot import grass.tools: without it every
# generated script dies with ModuleNotFoundError and every execution test fails.
if ! grass --tmp-mapset "$GRADER_HOME/grassdata/nc_basic_spm_grass7/" \
      --exec python3 -c "import grass.tools" ; then
  echo "ERROR: installed GRASS lacks grass.tools; GRASS 8.5+ is required." >&2
  exit 1
fi
echo "GRASS $(grass --version | head -1) with grass.tools available."

# ---------------------------------------------------------------------------
# 6. Python dependencies
# ---------------------------------------------------------------------------
pip install -q -r requirements.txt
pip install -q pytest

# ---------------------------------------------------------------------------
# 7. Run
# ---------------------------------------------------------------------------
# The operator account must own the checkout it writes caches and artifacts
# into, and must be able to reach the dataset through its own home directory.
REPO="$(pwd)"
chown -R "$GRADER:$GRADER" "$REPO"

if [ "$1" = "eval" ]; then
  su "$GRADER" -c "cd '$REPO' && HOME='$GRADER_HOME' python3 benchmarks/run_eval.py --model qwen2.5-coder:7b"
else
  # The full suite. Without GRASS and the dataset above, the `slow` tests
  # (test_executor.py, test_integration_smoke.py) skip themselves; with them
  # provisioned, they run for real.
  su "$GRADER" -c "cd '$REPO' && HOME='$GRADER_HOME' python3 -m pytest tests/ -q"
fi
