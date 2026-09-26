#!/bin/sh
# Prepare a clean checkout for building: Python packages, agbcc, and the legacy
# toolchain. Idempotent - each step is skipped if its output already exists.
#
# Installs nothing system-wide and never needs root. It opens by asking
# check_prerequisites.py --system-only what is missing, so the Arch package
# names live in exactly one place rather than being copied here where they drift.
#
# Supplying a base ROM is the one step left to you; ROMs are never fetched.
set -e

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"

# agbcc's build.sh and install.sh expand paths unquoted, as does the binutils
# 2.10 build, so a checkout path with whitespace fails deep inside make with a
# confusing error. Refuse it up front instead.
case $ROOT in
    *[[:space:]]*)
        echo "error: the checkout path contains whitespace: $ROOT" >&2
        echo "       agbcc and binutils 2.10 cannot build there; move or clone it elsewhere." >&2
        exit 1 ;;
esac

# Fixed rather than overridable: configure.py (upstream) and the docs both name
# .venv, so a venv anywhere else would be half-honoured.
VENV="$ROOT/.venv"
SHIM="$ROOT/build/shim"
AGBCC_SRC="${AGBCC_SRC:-$ROOT/../agbcc}"
AGBCC_REPO="${AGBCC_REPO:-https://github.com/pret/agbcc}"

say() { printf '\n== %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# -------------------------------------------------------- system packages ----
# Fail here, in seconds, rather than twenty minutes into building binutils
# 2.10 and agbcc from source.
say "System packages"
if ! python3 "$ROOT/tools/check_prerequisites.py" --system-only; then
    echo >&2
    echo "Install those first, then run this script again." >&2
    exit 1
fi

# ---------------------------------------------------------------- python ----
# Before configure.py: it resolves the report interpreter when it runs and bakes
# the result into build.ninja, so it only picks up .venv once .venv exists.
# (tools/build.sh reruns configure.py every time, so it is never stale there.)
#
# A venv is only reused if its own pip still runs. A checkout that was moved
# (pip's shebang names the old path), an interrupted first run (no pip at all)
# and an Arch Python minor upgrade (the venv's site-packages are for the old
# version) all leave an executable bin/python behind a venv that no longer works.
say "Python packages"
if ! "$VENV/bin/python" -m pip --version >/dev/null 2>&1; then
    if [ -e "$VENV" ]; then
        echo "recreating $VENV: its pip no longer runs"
    fi
    python3 -m venv --clear "$VENV"
fi
PY="$VENV/bin/python"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r "$ROOT/requirements.txt"
echo "ok: $PY"

# ---------------------------------------------------------- preprocessor ----
# configure.py bakes the literal name arm-none-eabi-cpp into build.ninja. It
# ships with the cross compiler rather than with binutils, and every call site
# passes -undef -nostdinc, so any C preprocessor produces the same output. Shim
# the host one instead of making 1.9 GiB of cross compiler a prerequisite.
#
# The shim has to still be on PATH when ninja runs, not merely while this script
# runs - which is why the build goes through tools/build.sh.
say "Cross preprocessor"
if have arm-none-eabi-cpp; then
    echo "ok: $(command -v arm-none-eabi-cpp)"
elif have cpp; then
    mkdir -p "$SHIM"
    printf '#!/bin/sh\nexec %s "$@"\n' "$(command -v cpp)" > "$SHIM/arm-none-eabi-cpp"
    chmod +x "$SHIM/arm-none-eabi-cpp"
    PATH="$SHIM:$PATH"
    export PATH
    # Prove it runs now, rather than discovering it as Error 127 at the first cc
    # rule of an otherwise long build.
    if ! "$SHIM/arm-none-eabi-cpp" --version >/dev/null 2>&1; then
        echo "error: the shim at $SHIM/arm-none-eabi-cpp does not run" >&2
        exit 1
    fi
    echo "ok: shimmed arm-none-eabi-cpp -> $(command -v cpp)"
else
    echo "error: no C preprocessor found; install gcc (base-devel)" >&2
    exit 1
fi

# ------------------------------------------------------------------ agbcc ----
say "agbcc"
if [ -f "$ROOT/tools/agbcc/bin/old_agbcc" ]; then
    echo "ok: already installed"
else
    if [ ! -d "$AGBCC_SRC" ]; then
        git clone --depth 1 "$AGBCC_REPO" "$AGBCC_SRC"
    fi

    # agbcc predates C99. GCC 14 made implicit function declarations, implicit
    # int, int conversions, incompatible pointer types and return mismatches
    # errors, and GCC 15 moved the default dialect to C23. Pass a permissive
    # compiler - but note build.sh expands $CCOPT unquoted, so CC has to be ONE
    # token or make reads the flags as build targets. Hence a wrapper.
    if [ -z "${CC:-}" ]; then
        WRAP="$ROOT/build/agbcc-cc"
        mkdir -p "$(dirname "$WRAP")"
        cat > "$WRAP" <<'WRAPPER'
#!/bin/sh
exec cc -std=gnu89 -fcommon \
  -Wno-implicit-function-declaration \
  -Wno-int-conversion \
  -Wno-return-mismatch \
  -Wno-incompatible-pointer-types \
  -Wno-builtin-declaration-mismatch \
  -Wno-implicit-int \
  "$@"
WRAPPER
        chmod +x "$WRAP"
        CC="$WRAP"
        export CC
        echo "using permissive CC wrapper: $WRAP"
    fi

    ( cd "$AGBCC_SRC" && ./build.sh && ./install.sh "$ROOT" )
    echo "ok: installed"
fi

# ----------------------------------------------------------------- gbagfx ----
# Required, not optional: tools/assetgen.py shells out to it for every
# tiles4/tiles8 and lz77 entry, so extract_assets.py - the step right after this
# script - stops with FileNotFoundError without it. It needs libpng and zlib,
# which the --system-only preflight above has already confirmed are installed.
say "gbagfx"
if [ -x "$ROOT/tools/gbagfx/gbagfx" ]; then
    echo "ok: already built"
else
    sh "$ROOT/tools/fetch_gbagfx.sh"
fi

# -------------------------------------------------------- legacy toolchain ----
# Skipped only when every file configure.py gates on exists. setup_legacy_toolchain.py
# installs the binaries before it builds the runtime libraries, so a failure in
# that second half leaves bin/ complete and lib/ empty - and a skip test that
# looked at bin/ alone would never repair it.
say "Legacy toolchain"
if [ -f "$ROOT/tools/legacy/bin/arm-elf-as" ] && [ -f "$ROOT/tools/legacy/bin/arm-elf-ld" ] \
    && [ -f "$ROOT/tools/legacy/lib/libgcc.a" ] && [ -f "$ROOT/tools/legacy/lib/libc.a" ]; then
    echo "ok: already built"
else
    "$PY" "$ROOT/tools/setup_legacy_toolchain.py"
fi

# ------------------------------------------------------------------- next ----
say "Status"
"$PY" "$ROOT/tools/check_prerequisites.py" || true

cat <<EOF

Next: supply a base ROM, then build.

  cp /path/to/your/dump roms/B8CE.gba
  $PY tools/extract_assets.py us
  tools/build.sh --version us

Build through tools/build.sh rather than a bare ninja. It puts the shim and
.venv/bin on PATH, which is what lets the two names configure.py bakes into
build.ninja resolve. To run ninja yourself instead:

  export PATH="$SHIM:$VENV/bin:\$PATH"

ROMs are never committed; roms/ is ignored.
EOF
