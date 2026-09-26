# Kingdom Hearts: Chain of Memories (GBA)

[![Build Status]][actions] [![us]][progress] [![jp]][progress] [![eu]][progress]

[Build Status]: https://github.com/pheenoh/khcom/actions/workflows/build.yml/badge.svg
[actions]: https://github.com/pheenoh/khcom/actions/workflows/build.yml

[us]: https://decomp.dev/pheenoh/khcom/us.svg?mode=shield&label=us
[jp]: https://decomp.dev/pheenoh/khcom/jp.svg?mode=shield&label=jp
[eu]: https://decomp.dev/pheenoh/khcom/eu.svg?mode=shield&label=eu
[progress]: https://decomp.dev/pheenoh/khcom

<!-- markdownlint-disable MD033 -->
[<img src="https://decomp.dev/pheenoh/khcom/us.svg?w=512&h=256" width="512" height="256" alt="Progress graph for the us version">][progress]
<!-- markdownlint-enable MD033 -->

A matching decompilation of *Kingdom Hearts: Chain of Memories*
for the Game Boy Advance.

> [!IMPORTANT]
> This repository does **not** contain any game assets or ROMs. An existing
> copy of the game is required to build.

> [!NOTE]
> This fork adds Arch Linux setup tooling on top of the decompilation: a
> prerequisite checker, an idempotent bootstrap, and a build wrapper that works
> without the ARM cross compiler. It does not change any decompiled source —
> see [CONTRIBUTING.md](CONTRIBUTING.md) to build from a clean checkout.

The project can target the following versions:

| Version | Code | SHA-1 |
|---------|------|-------|
| `us`    | B8CE | `10729bd884f8fdca7a310b6d606c52e46657aa48` |
| `jp`    | B8CJ | `59ec0a0a4ccd1e6acb3bbd7bfb21d63988958cfa` |
| `eu`    | B8CP | `8db73586cdb11b3795907edebf43228dbcd3e6b2` |

## Dependencies

On Arch Linux:

```sh
sudo pacman -S --needed base-devel git ninja python arm-none-eabi-binutils libpng zlib
```

`libpng` and `zlib` are what `gbagfx` links against, and asset extraction shells
out to `gbagfx`, so all of the above is needed. Everything else — the Python
packages in a virtualenv, `arm-none-eabi-cpp`, [agbcc](https://github.com/pret/agbcc)
and `gbagfx` itself — is handled by `tools/bootstrap.sh`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full from-scratch setup. The one
non-obvious part is `arm-none-eabi-cpp`: it is written into `build.ninja` as a
literal, so `CPP=cpp` does not stand in for it and `ninja` has to be run through
`tools/build.sh`.

## Building

- Clone the repository:

  ```sh
  git clone https://github.com/dexedrne/khcom.git
  ```

- Install the packages above, then bootstrap:

  ```sh
  sh tools/bootstrap.sh
  ```

- Copy your legally dumped ROM(s) into `roms/` as `<code>.gba` (e.g. `roms/B8CE.gba`).

- Extract assets and build:

  ```sh
  ./.venv/bin/python tools/extract_assets.py
  tools/build.sh
  ```

  To use a version other than `us`, specify it with `--version`:

  ```sh
  ./.venv/bin/python tools/extract_assets.py jp
  tools/build.sh --version jp
  ```

## License

This project is released under the [CC0 1.0 Universal](LICENSE.md) license.
