# Kingdom Hearts: Chain of Memories (GBA)

[![Build Status]][actions] [![us]][progress] [![jp]][progress] [![eu]][progress]

[Build Status]: https://github.com/pheenoh/khcom/actions/workflows/build.yml/badge.svg
[actions]: https://github.com/pheenoh/khcom/actions/workflows/build.yml

[us]: https://decomp.dev/pheenoh/khcom/us.svg?mode=shield&label=us
[jp]: https://decomp.dev/pheenoh/khcom/jp.svg?mode=shield&label=jp
[eu]: https://decomp.dev/pheenoh/khcom/eu.svg?mode=shield&label=eu
[progress]: https://decomp.dev/pheenoh/khcom

> **This is a fork.** The decompilation itself is upstream's work at
> [pheenoh/khcom](https://github.com/pheenoh/khcom); this fork only adds setup
> tooling, and tracks upstream for everything else.
>
> - `tools/bootstrap.sh` — one command from a clean checkout to a ready tree
> - `tools/check_prerequisites.py` — reports every missing dependency at once
> - `.github/workflows/first-run.yml` — CI for the from-scratch path
> - [`CONTRIBUTING.md`](CONTRIBUTING.md) — the setup walkthrough
>
> It also fixes two bugs that only bite a first build: `tools/fetch_gbagfx.sh`
> cloned a repository that returns 404, and `arm-none-eabi-cpp` was required but
> undocumented. Upstream's CI runs in a prebuilt image with the toolchain and
> base ROMs already present, so it never walks this path.
>
> No ROMs or extracted assets are distributed here; supply your own dump.

<!-- markdownlint-disable MD033 -->
[<img src="https://decomp.dev/pheenoh/khcom/us.svg?w=512&h=256" width="512" height="256" alt="Progress graph for the us version">][progress]
<!-- markdownlint-enable MD033 -->

A matching decompilation of *Kingdom Hearts: Chain of Memories*
for the Game Boy Advance.

> [!IMPORTANT]
> This repository does **not** contain any game assets or ROMs. An existing
> copy of the game is required to build.

The project can target the following versions:

| Version | Code | SHA-1 |
|---------|------|-------|
| `us`    | B8CE | `10729bd884f8fdca7a310b6d606c52e46657aa48` |
| `jp`    | B8CJ | `59ec0a0a4ccd1e6acb3bbd7bfb21d63988958cfa` |
| `eu`    | B8CP | `8db73586cdb11b3795907edebf43228dbcd3e6b2` |

## Dependencies

- git
- ninja
- python3
- `binutils-arm-none-eabi`
- `gcc-arm-none-eabi`, for `arm-none-eabi-cpp`. `tools/setup_legacy_toolchain.py`
  preprocesses the runtime library sources with it, and it ships with the cross
  compiler rather than with binutils. Without it the legacy assembler builds and
  then the runtime libraries fail with `Error 127`. Only the preprocessor is used,
  so setting `CPP` to any C preprocessor also works — the call site passes `-undef
  -nostdinc`, leaving nothing target-specific.
- [agbcc](https://github.com/pret/agbcc):

  ```sh
  git clone https://github.com/pret/agbcc
  cd agbcc && ./build.sh && ./install.sh ../khcom
  ```

## Building

- Clone the repository:

  ```sh
  git clone https://github.com/pheenoh/khcom.git
  ```

- Copy your legally dumped ROM(s) into `roms/` as `<code>.gba` (e.g. `roms/B8CE.gba`).

- Extract assets:

  ```sh
  python3 tools/extract_assets.py
  ```

- Configure:

  ```sh
  python3 configure.py
  ```

  To use a version other than `us`, specify it with `--version`.

- Build:

  ```sh
  ninja
  ```

## License

This project is released under the [CC0 1.0 Universal](LICENSE.md) license.
