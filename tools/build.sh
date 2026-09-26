#!/bin/sh
# Configure and build. Use this instead of a bare `ninja`.
#
#   tools/build.sh [configure.py options] [-- ninja arguments]
#   tools/build.sh --version jp
#   tools/build.sh --version us -- progress
#
# configure.py bakes two names into build.ninja that `ninja` on its own will not
# resolve on a box without the cross compiler:
#
#   arm-none-eabi-cpp  written as a literal from --binutils-prefix. It ships
#                      with arm-none-eabi-gcc, not with binutils, which is a
#                      267 MiB download / 1.9 GiB installed for one
#                      preprocessing step. tools/bootstrap.sh shims it to the
#                      host cpp, which is equivalent here because every call
#                      site passes -undef -nostdinc.
#
#                      Setting CPP=cpp does NOT fix this: nothing on the build
#                      path reads that variable.
#
#   python3            used bare by several rules, among them assetgen, which
#                      imports yaml. That lives in .venv, because PEP 668 means
#                      Arch will not take it system-wide, so .venv/bin goes
#                      first on PATH to make the bare name resolve to the venv.
#
# configure.py itself runs under the venv interpreter, so the report interpreter
# it bakes in - which runs mapfile_parser and regional_data.py - is the venv's.
set -e

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"

SHIM="$ROOT/build/shim"
VENV="$ROOT/.venv"

if [ ! -x "$VENV/bin/python" ]; then
    echo "error: no virtualenv at $VENV" >&2
    echo "       run tools/bootstrap.sh first." >&2
    exit 1
fi

if ! command -v arm-none-eabi-cpp >/dev/null 2>&1 && [ ! -x "$SHIM/arm-none-eabi-cpp" ]; then
    echo "error: no arm-none-eabi-cpp and no shim for it" >&2
    echo "       run tools/bootstrap.sh, or install arm-none-eabi-gcc." >&2
    exit 1
fi

PATH="$SHIM:$VENV/bin:$PATH"
export PATH

# Split the arguments at the first --: configure.py keeps what comes before it
# in "$@", and ninja gets what comes after. Ninja targets and flags never contain
# whitespace, so those can travel as one string and be word-split below.
targets=
split=
for arg do
    shift
    if [ -z "$split" ] && [ "$arg" = -- ]; then
        split=1
    elif [ -n "$split" ]; then
        targets="$targets $arg"
    else
        set -- "$@" "$arg"
    fi
done

# configure.py's --help exits 0, so without this a help request would go on to
# run ninja against whatever build.ninja was already there.
for arg do
    case $arg in
        -h|--help) exec "$VENV/bin/python" configure.py "$@" ;;
    esac
done

"$VENV/bin/python" configure.py "$@"
# Word splitting is the point here; see the comment on the split above.
# shellcheck disable=SC2086
ninja $targets
