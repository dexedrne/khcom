#!/bin/sh
set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
DEST="$ROOT/tools/gbagfx"

# gbagfx has no standalone upstream repository. It is maintained as a tool
# subdirectory inside the pret game decompilations, so fetch just that subtree
# rather than cloning a whole repo. Override either value to use a different
# source (for example pret/pokefirered, which carries an equivalent copy).
UPSTREAM="${GBAGFX_REPO:-https://github.com/pret/pokeemerald.git}"
SUBDIR="${GBAGFX_SUBDIR:-tools/gbagfx}"

if [ -x "$DEST/gbagfx" ]; then
    echo "gbagfx already present: $DEST/gbagfx"
    exit 0
fi

if [ ! -d "$DEST" ]; then
    WORK=$(mktemp -d)
    # shellcheck disable=SC2064  # expand WORK now, not at trap time
    trap "rm -rf '$WORK'" EXIT INT TERM

    git clone --depth 1 --filter=blob:none --sparse "$UPSTREAM" "$WORK/src"
    git -C "$WORK/src" sparse-checkout set --no-cone "$SUBDIR"

    if [ ! -d "$WORK/src/$SUBDIR" ]; then
        echo "error: '$SUBDIR' not found in $UPSTREAM" >&2
        exit 1
    fi

    mkdir -p "$(dirname "$DEST")"
    cp -R "$WORK/src/$SUBDIR" "$DEST"
fi

make -C "$DEST"
echo "built $DEST/gbagfx"
