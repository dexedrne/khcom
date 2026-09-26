#!/usr/bin/env python3
"""Report which build prerequisites are missing, before anything is built.

The setup steps fail at varying depths: a missing cross preprocessor only
surfaces as `Error 127` from a sub-make after the legacy assembler has already
been built, and a missing Python package only surfaces once configure.py runs.
This checks everything up front and says what to install.

Arch Linux is the target this is written for. Package hints are given as a
single pacman command on Arch, and as the canonical tool names everywhere else:
guessing an apt/fedora package name that may not exist is worse than naming the
tool and saying nothing about how to get it.

Exits 0 when the tree is ready to build, 1 when something required is missing.
Optional items are reported but never fail the run.
"""

import argparse
import ast
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ARCH = 'arch'
GENERIC = 'generic'

OS_RELEASE = Path('/etc/os-release')

# (executable, Arch package, why it is needed)
HOST_TOOLS = [
    ('git', 'git', 'cloning agbcc and the gbagfx subtree'),
    ('ninja', 'ninja', 'the build itself'),
    ('make', 'base-devel', 'building agbcc and the runtime libraries'),
    ('bash', 'base-devel', 'SHELL for the runtime library recipes'),
    ('tar', 'tar', 'unpacking the pinned toolchain sources'),
    ('cc', 'base-devel', 'building the host tools'),
]

CROSS_TOOLS = [
    ('arm-none-eabi-as', 'arm-none-eabi-binutils', 'assembling maintained sources'),
    ('arm-none-eabi-ar', 'arm-none-eabi-binutils', 'archiving the runtime libraries'),
    ('arm-none-eabi-ld', 'arm-none-eabi-binutils', 'linking'),
    ('arm-none-eabi-objcopy', 'arm-none-eabi-binutils', 'producing the ROM image'),
]

# (module, requirements.txt name, why it is needed)
#
# All three are imported by code the first-run path actually reaches:
# mapfile_parser backs the report rule and the frontends pull in decomp_settings
# with it, and tools/extract_assets.py imports yaml. A checker that omits yaml
# passes a tree that then dies in extract_assets.py.
PYTHON_PACKAGES = [
    ('mapfile_parser', 'mapfile-parser', 'the progress report configure.py wires up'),
    ('yaml', 'pyyaml', 'tools/extract_assets.py and tools/assetgen.py'),
    ('decomp_settings', 'decomp-settings', 'reading decomp.yaml, via mapfile_parser'),
]

# (pkg-config name, header, Arch package, why) - needed to build gbagfx, which
# tools/extract_assets.py cannot run without. On Arch the headers ship inside the
# library package itself, so one name covers both halves.
GFX_LIBRARIES = [
    ('libpng', 'png.h', 'libpng', 'gbagfx reads and writes PNGs'),
    ('zlib', 'zlib.h', 'zlib', 'gbagfx compresses with it'),
]

INSTALL = {ARCH: 'sudo pacman -S --needed'}

# Kept only so a tree whose configure.py cannot be read still gets checked.
FALLBACK_VERSIONS = {
    'us': ('B8CE', '10729bd884f8fdca7a310b6d606c52e46657aa48'),
    'jp': ('B8CJ', '59ec0a0a4ccd1e6acb3bbd7bfb21d63988958cfa'),
    'eu': ('B8CP', '8db73586cdb11b3795907edebf43228dbcd3e6b2'),
}


def load_versions(root=None):
    """Read VERSIONS out of configure.py so the table cannot drift from it.

    A hand-copied table is how this tooling went stale once already: upstream
    changed the file and the copy here did not follow. Falls back to the copy
    above if configure.py is unreadable or no longer holds the assignment, so
    this can never itself be the reason a check fails.
    """
    root = ROOT if root is None else root
    try:
        tree = ast.parse((root / 'configure.py').read_text())
    except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
        return dict(FALLBACK_VERSIONS)

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == 'VERSIONS' for t in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except ValueError:
            return dict(FALLBACK_VERSIONS)
        if isinstance(value, dict) and value:
            return {str(k): tuple(v) for k, v in value.items()}

    return dict(FALLBACK_VERSIONS)


VERSIONS = load_versions()


def detect_distro(text=None):
    """'arch' for Arch and its derivatives, 'generic' for everything else.

    Takes the os-release text so the tests never depend on the host, and never
    raises: an unreadable or malformed file is 'generic', which only means the
    hints fall back to canonical tool names.
    """
    if text is None:
        try:
            text = OS_RELEASE.read_text()
        except OSError:
            return GENERIC

    identifier, like = '', ''
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('ID='):
            identifier = line[3:].strip().strip('"').lower()
        elif line.startswith('ID_LIKE='):
            like = line[8:].strip().strip('"').lower()

    if identifier == 'arch' or 'arch' in like.split():
        return ARCH
    return GENERIC


def install_command(packages, distro=None):
    """One copy-pasteable command, or None when there is no honest one to give.

    Only Arch package names are known here, so only Arch gets a command.
    """
    distro = detect_distro() if distro is None else distro
    unique = sorted({name for name in packages if name})
    if not unique or distro != ARCH:
        return None
    return '{} {}'.format(INSTALL[ARCH], ' '.join(unique))


class Report:
    def __init__(self, quiet=False):
        self.failures = []
        self.notes = []
        # Arch packages behind the failures, collected so the hints can be
        # collapsed into one command instead of one line per missing tool.
        self.packages = []
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
            report.packages.append(package)
            report.missing(name, why)


def check_preprocessor(report):
    """configure.py bakes the literal name into build.ninja, so it must resolve.

    `arm-none-eabi-cpp` ships with the cross compiler rather than with binutils.
    bootstrap.sh shims it to the host cpp, which is equivalent because every call
    site preprocesses with -undef -nostdinc.

    `CPP` is deliberately not consulted, because nothing on the build path reads
    it: configure.py bakes `arm-none-eabi-cpp` into build.ninja, and
    tools/setup_legacy_toolchain.py passes `CPP=arm-none-eabi-cpp` to make
    literally. A tree with CPP=cpp and neither the cross cpp nor the shim fails
    with `Error 127`. Accepting an override here once let that tree report ready.
    """
    found = shutil.which('arm-none-eabi-cpp')
    shim = ROOT / 'build/shim/arm-none-eabi-cpp'
    if found:
        report.ok('arm-none-eabi-cpp', found)
    elif shim.is_file() and os.access(shim, os.X_OK):
        # A note, not a failure: the tree builds via tools/build.sh, and making
        # this fatal would mean the no-cross-compiler path could never be green.
        report.note(
            'arm-none-eabi-cpp',
            'not on PATH, but {} shims it. Build with tools/build.sh. '
            'CPP=cpp does not cover ninja: configure.py bakes the literal name '
            'into build.ninja.'.format(shim.relative_to(ROOT)),
        )
    else:
        report.missing(
            'arm-none-eabi-cpp',
            'run tools/bootstrap.sh, which shims the host cpp; installing '
            'arm-none-eabi-gcc also provides it at ~1.9 GiB installed',
        )

    override = os.environ.get('CPP')
    if override:
        report.note(
            'CPP={}'.format(override),
            'ignored - configure.py and tools/setup_legacy_toolchain.py both run '
            'arm-none-eabi-cpp by name',
        )


def check_preprocessor_source(report):
    """Is there a C preprocessor to shim, before the shim exists?

    Only meaningful for --system-only, which runs before bootstrap: at that
    point a missing arm-none-eabi-cpp is expected, because the shim that stands
    in for it has not been written yet. bootstrap.sh shims whatever `cpp`
    resolves to and never reads CPP, so neither does this.
    """
    for name in ('arm-none-eabi-cpp', 'cpp'):
        found = shutil.which(name)
        if found:
            report.ok('C preprocessor', found)
            return
    report.packages.append('base-devel')
    report.missing('C preprocessor', 'need cpp, from gcc in base-devel')


def venv_python(root=None):
    """The interpreter a bootstrapped tree keeps its packages in."""
    root = ROOT if root is None else root
    for name in ('python3', 'python'):
        candidate = root / '.venv/bin' / name
        if candidate.exists():
            return candidate
    return None


def _can_import(python, module):
    try:
        return subprocess.run(
            [str(python), '-c', 'import ' + module],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ).returncode == 0
    except OSError:
        return False


def check_python_packages(report):
    """Probe the venv, not whichever interpreter is running this script.

    Importing against the running interpreter reported every package missing on
    a correctly bootstrapped tree, because they live in .venv. That sent people
    to `pip install` on an Arch box, which PEP 668 refuses outright.
    """
    python = venv_python()
    if python is None:
        # A failure, not a note: the very next documented commands are
        # .venv/bin/python tools/extract_assets.py and tools/build.sh, and
        # neither can run without it.
        report.missing(
            '.venv',
            'run tools/bootstrap.sh - tools/extract_assets.py and tools/build.sh '
            'both run from it',
        )
        return

    for module, package, why in PYTHON_PACKAGES:
        if _can_import(python, module):
            report.ok(module, why)
        else:
            report.missing(
                module,
                '{}, missing from .venv - run tools/bootstrap.sh '
                '(or .venv/bin/pip install -r requirements.txt)'.format(why),
            )


def check_agbcc(report):
    compiler = ROOT / 'tools/agbcc/bin/old_agbcc'
    if compiler.is_file():
        report.ok('agbcc', str(compiler))
    else:
        report.missing(
            'agbcc',
            'run tools/bootstrap.sh, or clone https://github.com/pret/agbcc and '
            './build.sh && ./install.sh ' + str(ROOT),
        )


# The set configure.py gates on. bootstrap.sh skips its legacy step only when all
# four exist, for the same reason.
LEGACY_TOOLCHAIN = [
    'tools/legacy/bin/arm-elf-as',
    'tools/legacy/bin/arm-elf-ld',
    'tools/legacy/lib/libgcc.a',
    'tools/legacy/lib/libc.a',
]


def check_legacy_toolchain(report):
    """configure.py refuses to run without all four files, so this fails too.

    It was once a note, which let a tree whose runtime-library build had failed
    - binaries installed, libraries not - report ready, and configure.py then
    refused it.
    """
    absent = [name for name in LEGACY_TOOLCHAIN if not (ROOT / name).is_file()]
    if not absent:
        report.ok('legacy toolchain', str(ROOT / 'tools/legacy'))
    else:
        report.missing(
            'legacy toolchain',
            'missing {} - run tools/bootstrap.sh (or tools/setup_legacy_toolchain.py)'.format(
                ', '.join(absent)
            ),
        )


def check_legacy_versions(report):
    """configure.py refuses anything but binutils 2.10, so name it here first.

    Separate from check_legacy_toolchain so that a caller which only has the
    paths (the unit tests) does not have to produce a runnable binary.
    """
    for name, expected in (
        ('tools/legacy/bin/arm-elf-as', 'GNU assembler 2.10'),
        ('tools/legacy/bin/arm-elf-ld', 'GNU ld 2.10'),
    ):
        path = ROOT / name
        if not path.is_file():
            continue  # check_legacy_toolchain has already reported it
        if not os.access(path, os.X_OK):
            # configure.py would die on this with a PermissionError traceback.
            report.missing(name, 'not executable - rerun tools/setup_legacy_toolchain.py')
            continue
        try:
            first = subprocess.check_output(
                [str(path), '--version'], text=True, stderr=subprocess.DEVNULL
            ).splitlines()[0]
        except (OSError, subprocess.CalledProcessError, IndexError):
            report.missing(name, 'could not read its version')
            continue
        if first == expected:
            report.ok(name, first)
        else:
            report.missing(
                name, 'expected "{}", got "{}" - rerun tools/setup_legacy_toolchain.py'.format(
                    expected, first
                )
            )


def sha1_of(path):
    digest = hashlib.sha1()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def rom_candidates(version, code):
    """Where the build takes a base ROM from, in order - tools/baserom.py's list.

    A dump in roms/ first; failing that, the ROM a previous matching build left
    at build/<version>/verified.gba, which extract_assets.py and the build both
    accept. Like baserom.load, the first one that exists is the one used, and a
    wrong hash there is an error rather than a reason to look further.
    """
    return [ROOT / 'roms' / (code + '.gba'), ROOT / 'build' / version / 'verified.gba']


def check_roms(report, versions):
    found_any = False
    for version in versions:
        code, expected = VERSIONS[version]
        rom = next((path for path in rom_candidates(version, code) if path.is_file()), None)
        if rom is None:
            report.note(
                'roms/{}.gba'.format(code),
                'absent - supply your own dump to build "{}"'.format(version),
            )
            continue
        found_any = True
        label = str(rom.relative_to(ROOT))
        actual = sha1_of(rom)
        if actual == expected:
            report.ok(label, 'sha1 matches ' + version)
        else:
            report.missing(
                label,
                'sha1 mismatch\n             expected {}\n             actual   {}'.format(
                    expected, actual
                ),
            )
    if not found_any:
        report.missing(
            'base ROM',
            'place at least one dump in roms/ as <code>.gba (for example roms/B8CE.gba)',
        )


def library_available(package, header):
    """Are a C library's headers installed, i.e. can gbagfx be built on it?

    pkg-config answers this exactly and ships in base-devel; the header probe is
    for a tree without it. On Arch a library's headers come in the package that
    provides the shared object, so /usr/include is the whole story.
    """
    try:
        done = subprocess.run(
            ['pkg-config', '--exists', package],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass
    else:
        return done.returncode == 0
    return (Path('/usr/include') / header).exists()


def gbagfx_built(root=None):
    """Is the gbagfx binary there and runnable?

    Both the binary check and the library check need this, and the library check
    is only meaningful without it.
    """
    root = ROOT if root is None else root
    binary = root / 'tools/gbagfx/gbagfx'
    return binary.is_file() and os.access(binary, os.X_OK)


def check_gfx_libraries(report):
    """libpng and zlib, but only while gbagfx still has to be built from source.

    This is a system-package check, so it runs in --system-only too: a missing
    header otherwise surfaces as `png.h: No such file or directory` from make,
    after the bootstrap has already spent minutes on agbcc.

    A tree that already has the gbagfx binary is skipped entirely rather than
    reported clean, because the libraries are only needed to compile it - and on
    Arch a library that is present at runtime brought its headers with it, so
    the two cannot come apart.
    """
    if gbagfx_built():
        return

    for package, header, arch, why in GFX_LIBRARIES:
        if library_available(package, header):
            report.ok(package, why)
        else:
            report.packages.append(arch)
            report.missing(
                '{} ({})'.format(package, header),
                'needed to build gbagfx - install {}'.format(arch),
            )


def check_gbagfx(report):
    """gbagfx is required, not optional.

    tools/assetgen.py shells out to it from decode_one for every tiles4/tiles8
    and lz77 entry, and those cover the sprite manifests, so tools/extract_assets.py
    - a mandatory first step - stops with FileNotFoundError without it.
    configure.py lists the binary as an implicit input of the asset rule as well.

    This was documented as optional, which let a tree report 'all prerequisites
    satisfied' and then fail on the very next command it suggested.
    """
    if gbagfx_built():
        report.ok('gbagfx', str(ROOT / 'tools/gbagfx/gbagfx'))
    else:
        report.missing('gbagfx', 'run sh tools/fetch_gbagfx.sh')


def collect(report, versions, system_only=False):
    """Run every check into one report.

    system_only stops after the system packages bootstrap.sh cannot install
    itself. Checking the rest there would only report the work it is about to do.
    """
    if not report.quiet:
        print('host tools')
    check_executables(report, HOST_TOOLS)

    if not report.quiet:
        print('cross binutils')
    check_executables(report, CROSS_TOOLS)

    # The preprocessor belongs to the group above, and --system-only swaps in a
    # variant that does not expect the shim, which does not exist yet at that point.
    if system_only:
        check_preprocessor_source(report)
    else:
        check_preprocessor(report)

    # Skipped entirely when gbagfx is built, so the heading is only printed when
    # there is something to put under it.
    if not gbagfx_built():
        if not report.quiet:
            print('gfx libraries')
        check_gfx_libraries(report)

    if system_only:
        return

    if not report.quiet:
        print('python packages')
    check_python_packages(report)

    if not report.quiet:
        print('toolchain')
    check_agbcc(report)
    check_legacy_toolchain(report)
    check_legacy_versions(report)

    if not report.quiet:
        print('assets')
    check_gbagfx(report)

    if not report.quiet:
        print('base ROMs')
    check_roms(report, versions)


def finish(report, system_only=False):
    print()
    if report.failures:
        print('{} prerequisite(s) missing:'.format(len(report.failures)))
        for label, fix in report.failures:
            print('  - {}: {}'.format(label, fix))
        command = install_command(report.packages)
        if command:
            print()
            print('on Arch:')
            print('  {}'.format(command))
        elif report.packages:
            print()
            print('install the packages that provide the tools above.')
        return 1

    print('system packages satisfied' if system_only else 'all prerequisites satisfied')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # Validated by hand rather than with choices=. Combining nargs='*' with
    # choices= makes argparse check the default too on some versions, so either
    # default leaks "[]" into the usage line or an empty argv is rejected
    # outright, depending on the interpreter.
    parser.add_argument(
        'versions',
        nargs='*',
        metavar='{{{}}}'.format(','.join(sorted(VERSIONS))),
        help='versions whose base ROMs to check (default: all)',
    )
    parser.add_argument('-q', '--quiet', action='store_true', help='only print problems')
    parser.add_argument(
        '--system-only',
        action='store_true',
        help='check only the system packages tools/bootstrap.sh cannot install itself',
    )
    args = parser.parse_args()

    unknown = [v for v in args.versions if v not in VERSIONS]
    if unknown:
        parser.error(
            'invalid version(s): {} (choose from {})'.format(
                ', '.join(unknown), ', '.join(sorted(VERSIONS))
            )
        )
    versions = args.versions or sorted(VERSIONS)

    report = Report(quiet=args.quiet)
    collect(report, versions, system_only=args.system_only)
    return finish(report, system_only=args.system_only)


if __name__ == '__main__':
    sys.exit(main())
