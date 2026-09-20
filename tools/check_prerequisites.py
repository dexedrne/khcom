#!/usr/bin/env python3
"""Report which build prerequisites are missing, before anything is built.

The setup steps fail at varying depths: a missing cross preprocessor only
surfaces as `Error 127` from a sub-make after the legacy assembler has already
been built, and a missing Python package only surfaces once configure.py runs.
This checks everything up front and says what to install.

Exits 0 when the tree is ready to build, 1 when something required is missing.
Optional items are reported but never fail the run.
"""

import argparse
import hashlib
import importlib.util
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (executable, package hint, why it is needed)
HOST_TOOLS = [
    ('git', 'git', 'cloning agbcc and the gbagfx subtree'),
    ('ninja', 'ninja', 'the build itself'),
    ('make', 'make', 'building agbcc and the runtime libraries'),
    ('bash', 'bash', 'SHELL for the runtime library recipes'),
    ('tar', 'tar', 'unpacking the pinned toolchain sources'),
    ('cc', 'a C compiler', 'building the host tools'),
]

CROSS_TOOLS = [
    ('arm-none-eabi-as', 'binutils-arm-none-eabi', 'assembling maintained sources'),
    ('arm-none-eabi-ar', 'binutils-arm-none-eabi', 'archiving the runtime libraries'),
    ('arm-none-eabi-ld', 'binutils-arm-none-eabi', 'linking'),
    ('arm-none-eabi-objcopy', 'binutils-arm-none-eabi', 'producing the ROM image'),
]

PYTHON_PACKAGES = [
    ('mapfile_parser', 'mapfile-parser', 'progress reporting and symbol checks'),
    ('decomp_settings', 'decomp-settings', 'reading decomp.yaml'),
]

VERSIONS = {
    'us': ('B8CE', '10729bd884f8fdca7a310b6d606c52e46657aa48'),
    'jp': ('B8CJ', '59ec0a0a4ccd1e6acb3bbd7bfb21d63988958cfa'),
    'eu': ('B8CP', '8db73586cdb11b3795907edebf43228dbcd3e6b2'),
}


class Report:
    def __init__(self, quiet=False):
        self.failures = []
        self.notes = []
        self.quiet = quiet

    def ok(self, label, detail=''):
        if not self.quiet:
            print('  ok       {}{}'.format(label, '  ' + detail if detail else ''))

    def missing(self, label, fix):
        self.failures.append((label, fix))
        print('  MISSING  {}'.format(label))

    def note(self, label, detail):
        self.notes.append((label, detail))
        if not self.quiet:
            print('  note     {}  {}'.format(label, detail))


def check_executables(report, entries):
    for name, package, why in entries:
        path = shutil.which(name)
        if path:
            report.ok(name, path)
        else:
            report.missing(name, 'install {} ({})'.format(package, why))


def check_preprocessor(report):
    """The runtime libraries need a C preprocessor for -x assembler-with-cpp.

    setup_legacy_toolchain.py passes CPP=arm-none-eabi-cpp. That call site uses
    -undef -nostdinc, so nothing target-specific is involved and any C
    preprocessor produces the same output; the cross one is simply the default.
    """
    override = os.environ.get('CPP')
    if override:
        exe = override.split()[0]
        if shutil.which(exe):
            report.ok('CPP override', override)
            return
        report.missing('CPP={}'.format(override), 'the CPP override is not executable')
        return

    if shutil.which('arm-none-eabi-cpp'):
        report.ok('arm-none-eabi-cpp', shutil.which('arm-none-eabi-cpp'))
        return

    fix = 'install gcc-arm-none-eabi (ships arm-none-eabi-cpp; binutils does not)'
    if shutil.which('cpp'):
        fix += ', or set CPP=cpp to use the host preprocessor'
    report.missing('arm-none-eabi-cpp', fix)


def check_python_packages(report):
    for module, package, why in PYTHON_PACKAGES:
        if importlib.util.find_spec(module) is not None:
            report.ok(module, why)
        else:
            report.missing(module, 'pip install {} ({})'.format(package, why))


def check_agbcc(report):
    compiler = ROOT / 'tools/agbcc/bin/old_agbcc'
    if compiler.is_file():
        report.ok('agbcc', str(compiler))
    else:
        report.missing(
            'agbcc',
            'clone https://github.com/pret/agbcc, then ./build.sh && ./install.sh ' + str(ROOT),
        )


def check_legacy_toolchain(report):
    """Mirror the set configure.py gates on, so this agrees with that check."""
    required = [
        'tools/legacy/bin/arm-elf-as',
        'tools/legacy/bin/arm-elf-ld',
        'tools/legacy/lib/libgcc.a',
        'tools/legacy/lib/libc.a',
    ]
    absent = [name for name in required if not (ROOT / name).is_file()]
    if not absent:
        report.ok('legacy toolchain', str(ROOT / 'tools/legacy'))
    else:
        report.note(
            'legacy toolchain',
            'missing {} - run tools/setup_legacy_toolchain.py'.format(', '.join(absent)),
        )


def sha1_of(path):
    digest = hashlib.sha1()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def check_roms(report, versions):
    found_any = False
    for version in versions:
        code, expected = VERSIONS[version]
        rom = ROOT / 'roms' / (code + '.gba')
        if not rom.is_file():
            report.note(
                'roms/{}.gba'.format(code),
                'absent - supply your own dump to build "{}"'.format(version),
            )
            continue
        found_any = True
        actual = sha1_of(rom)
        if actual == expected:
            report.ok('roms/{}.gba'.format(code), 'sha1 matches ' + version)
        else:
            report.missing(
                'roms/{}.gba'.format(code),
                'sha1 mismatch\n             expected {}\n             actual   {}'.format(
                    expected, actual
                ),
            )
    if not found_any:
        report.missing(
            'base ROM',
            'place at least one dump in roms/ as <code>.gba (for example roms/B8CE.gba)',
        )


def check_git_available_for_gbagfx(report):
    """gbagfx is optional: every asset_gfx flag defaults to the baserom slice."""
    gbagfx = ROOT / 'tools/gbagfx/gbagfx'
    if gbagfx.is_file():
        report.ok('gbagfx', str(gbagfx))
    else:
        report.note('gbagfx', 'optional - only needed for the built-mega asset paths')


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # default=[] rather than the full list: with nargs='*' argparse validates a
    # non-empty default against choices, which would leak "[]" into the usage line.
    parser.add_argument(
        'versions',
        nargs='*',
        choices=sorted(VERSIONS),
        default=[],
        help='versions whose base ROMs to check (default: all)',
    )
    parser.add_argument('-q', '--quiet', action='store_true', help='only print problems')
    args = parser.parse_args()
    versions = args.versions or sorted(VERSIONS)

    report = Report(quiet=args.quiet)

    if not args.quiet:
        print('host tools')
    check_executables(report, HOST_TOOLS)

    if not args.quiet:
        print('cross binutils')
    check_executables(report, CROSS_TOOLS)
    check_preprocessor(report)

    if not args.quiet:
        print('python packages')
    check_python_packages(report)

    if not args.quiet:
        print('toolchain')
    check_agbcc(report)
    check_legacy_toolchain(report)
    check_git_available_for_gbagfx(report)

    if not args.quiet:
        print('base ROMs')
    check_roms(report, versions)

    print()
    if report.failures:
        print('{} prerequisite(s) missing:'.format(len(report.failures)))
        for label, fix in report.failures:
            print('  - {}: {}'.format(label, fix))
        return 1

    print('all prerequisites satisfied')
    return 0


if __name__ == '__main__':
    sys.exit(main())
