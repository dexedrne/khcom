#!/bin/sh
# Prepare a clean checkout for building: Python packages, agbcc, and the legacy
# toolchain. Idempotent - each step is skipped if its output already exists.
#
# Does not install system packages and never needs root. Run
# tools/check_prerequisites.py first to see what your package manager owes you.
#
# Supplying a base ROM is the one step left to you; ROMs are never fetched.
set -e

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"

VENV="${VENV:-$ROOT/.venv}"
AGBCC_SRC="${AGBCC_SRC:-$ROOT/../agbcc}"
AGBCC_REPO="${AGBCC_REPO:-https://github.com/pret/agbcc}"

say() { printf '\n== %s\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

# ---------------------------------------------------------------- python ----
say "Python packages"
if [ ! -x "$VENV/bin/python" ]; then
    python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$ROOT/requirements.txt"
PY="$VENV/bin/python"
echo "ok: $PY"

# ------------------------------------------------------------ preprocessor ----
# setup_legacy_toolchain.py invokes arm-none-eabi-cpp. It ships with the cross
# compiler rather than binutils, and is used only with -undef -nostdinc, so any
# C preprocessor is equivalent. Shim to the host one rather than make the whole
# cross compiler a hard requirement.
say "Cross preprocessor"
if have arm-none-eabi-cpp; then
    echo "ok: $(command -v arm-none-eabi-cpp)"
elif [ -n "${CPP:-}" ]; then
    echo "ok: using CPP=$CPP"
elif have cpp; then
    SHIM="$ROOT/build/shim"
    mkdir -p "$SHIM"
    printf '#!/bin/sh\nexec %s "$@"\n' "$(command -v cpp)" > "$SHIM/arm-none-eabi-cpp"
    chmod +x "$SHIM/arm-none-eabi-cpp"
    PATH="$SHIM:$PATH"
    export PATH
    echo "ok: shimmed arm-none-eabi-cpp -> $(command -v cpp)"
else
    echo "error: no C preprocessor found; install gcc-arm-none-eabi" >&2
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

    # agbcc predates C99. GCC 14 made implicit function declarations and int
    # conversions errors, and GCC 15 did the same for return mismatches. Pass a
    # permissive compiler - but note build.sh expands $CCOPT unquoted, so CC has
    # to be ONE token or make reads the flags as build targets. Hence a wrapper.
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

# -------------------------------------------------------- legacy toolchain ----
say "Legacy toolchain"
if [ -f "$ROOT/tools/legacy/bin/arm-elf-as" ] && [ -f "$ROOT/tools/legacy/bin/arm-elf-ld" ]; then
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
  $PY configure.py
  ninja

ROMs are never committed; roms/ is ignored.
EOF
