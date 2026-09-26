# Contributing

## Checking your environment

Before building anything, run:

```sh
python3 tools/check_prerequisites.py
```

It reports every missing prerequisite at once and exits non-zero if the tree
cannot be built yet. Several setup failures otherwise surface late and with
unhelpful messages — a missing cross preprocessor, for example, only appears as
`Error 127` from a sub-make after the legacy assembler has already built
successfully.

Add `--system-only` to check just the packages your package manager owes you.
That is the subset `tools/bootstrap.sh` cannot install for you, and it is the
same check the bootstrap runs before it starts.

## First build, from a clean checkout

These instructions are for Arch Linux, and the package names below are Arch's.

1. **Install the host and cross tools.**

   ```sh
   sudo pacman -S --needed base-devel git ninja python arm-none-eabi-binutils libpng zlib
   ```

   `libpng` and `zlib` are what `gbagfx` links against, and asset extraction
   needs `gbagfx`, so they belong in this list rather than in an optional one.

2. **Run the bootstrap.**

   ```sh
   sh tools/bootstrap.sh
   ```

   It creates `.venv` and installs `requirements.txt` into it, clones and builds
   [agbcc](https://github.com/pret/agbcc) beside the checkout, builds the pinned
   binutils 2.10 toolchain, and shims the cross preprocessor. It is idempotent,
   installs nothing system-wide and never needs root.

   Run it before `configure.py`. When `configure.py` runs, it bakes into
   `build.ninja` the interpreter that the report and regional-data checks use,
   choosing `.venv/bin/python3` only if it already exists. If you did configure
   first, configuring again fixes it — and `tools/build.sh` reconfigures on every
   run.

3. **Supply a base ROM.** Copy your own dump into `roms/` named for its game
   code, for example `roms/B8CE.gba`. ROMs are never committed and are listed in
   `.gitignore`. `tools/check_prerequisites.py` verifies its SHA-1 against
   `configure.py`'s version table, which holds the same values as the table in
   `README.md`.

4. **Extract the assets, then build.**

   ```sh
   ./.venv/bin/python tools/extract_assets.py us
   tools/build.sh --version us
   ```

   `configure.py` refuses to run until the legacy assembler exists, so keep that
   order.

### Build through `tools/build.sh`, not a bare `ninja`

`configure.py` bakes two names into `build.ninja` that a plain `ninja` will not
resolve:

- **`arm-none-eabi-cpp`**, written as a literal from `--binutils-prefix`. It
  ships with `arm-none-eabi-gcc`, not with `arm-none-eabi-binutils`, and the
  whole cross compiler is a 267 MiB download / 1.9 GiB installed for what is one
  preprocessing step. `tools/bootstrap.sh` shims it to your host `cpp`, which is
  equivalent because every call site passes `-undef -nostdinc`.

  **`CPP=cpp` does not substitute for this.** Nothing on the build path reads
  that variable: `configure.py` bakes the name into `build.ninja`, and
  `tools/setup_legacy_toolchain.py` passes `CPP=arm-none-eabi-cpp` to `make`
  literally. A tree that sets it and then runs `ninja` still fails with
  `Error 127` at the first `cc` rule. The shim has to be on `PATH` when `ninja`
  runs, which is what `build.sh` arranges.

- **`python3`**, used bare by several rules, among them `assetgen`, which
  imports `yaml`. That lives in `.venv`, so `.venv/bin` goes first on `PATH` to
  make the bare name resolve to the virtualenv. (`mapfile_parser` runs through
  the interpreter `configure.py` bakes in instead — see step 2.)

Arguments after `--` go to `ninja` rather than to `configure.py`:

```sh
tools/build.sh --version us -- -j4
```

If you would rather run `ninja` yourself:

```sh
export PATH="$PWD/build/shim:$PWD/.venv/bin:$PATH"
```

## Verifying a build

The build verifies itself. After linking, it compares the ROM against the SHA-1
that `configure.py`'s version table holds for that version and fails if they
differ, so a build that exits 0 is a matching build. Script against the exit
status of `tools/build.sh`. A match also copies the ROM to
`build/<version>/verified.gba`, but don't test for that file: an earlier copy
survives a later failed build, and the copy is made before the last regional-data
check, which can still fail.

To confirm the build is genuinely compiling sources rather than reusing your
base ROM, change any statement in a file under `src/`, run `tools/build.sh`, and
watch the hash check fail. Restore with:

```sh
git checkout -- <file>
rm -f build/<version>/verified.gba build/<version>/ok
tools/build.sh --version <version>
```

## gbagfx

`tools/extract_assets.py` shells out to `tools/gbagfx/gbagfx` for every
`tiles4`/`tiles8` and `lz77` entry, and those cover the sprite manifests, so
extraction stops with `FileNotFoundError` unless it has been built. `configure.py`
lists the binary as an implicit input of the asset rule as well. It is required,
and `tools/bootstrap.sh` builds it.

To build it on its own:

```sh
sh tools/fetch_gbagfx.sh
```

It has no standalone upstream repository, so the script sparse-checks-out the
tool subdirectory from a pret game decompilation.

gbagfx links against libpng and zlib, so their headers must be present or the
build stops at `png.h: No such file or directory`. On Arch they ship inside the
library packages themselves — there is no `-dev` split, so step 1 above already
covers it:

```sh
sudo pacman -S --needed libpng zlib
```

Because extraction runs before `configure.py`, a missing gbagfx surfaces as a
Python traceback rather than as a build error. `tools/check_prerequisites.py`
checks for it, and for the libraries while it still has to be built.

## Progress reporting

The default build does not produce a progress report, but `build.ninja` has a
target for it:

```sh
tools/build.sh --version us -- progress
```

That builds `build/us/report.json` with `mapfile_parser` from `.venv` (which
first needs a matching build) and summarizes it with `tools/progress.py`.
Published figures live on the decomp.dev page linked from `README.md`.

## Before opening a pull request

- Build and confirm it still matches for every version whose base ROM you have.
  CI builds `us`, `jp` and `eu`.
- Keep the working tree clean of build output. Everything generated by the steps
  above is already covered by `.gitignore`.
- The main build workflow runs in a prebuilt, apt-based image that supplies
  agbcc and its own `arm-none-eabi-cpp`, so it never exercises agbcc's source
  build, the Arch packages or the host-`cpp` shim. `.github/workflows/first-run.yml` covers
  that: on a stock `archlinux:latest` it runs the prerequisite checker and its
  tests, then the real bootstrap from source with no cache, then every unit test.
  It deliberately does not install `arm-none-eabi-gcc`, so the shim path is the
  one under test.
