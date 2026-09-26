import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import check_prerequisites as cp


class ReportTest(unittest.TestCase):
    def test_only_missing_entries_are_failures(self):
        report = cp.Report(quiet=True)
        report.ok('present')
        report.note('optional', 'not built yet')
        report.missing('absent', 'install it')
        self.assertEqual([label for label, _ in report.failures], ['absent'])
        self.assertEqual([label for label, _ in report.notes], ['optional'])


class PreprocessorSourceTest(unittest.TestCase):
    """--system-only, before the shim exists: is there a cpp to shim?"""

    def test_a_cpp_override_does_not_count(self):
        # bootstrap.sh shims whatever `cpp` resolves to and never reads CPP.
        with mock.patch.dict(os.environ, {'CPP': 'sh'}), \
                mock.patch.object(cp.shutil, 'which', return_value=None):
            report = cp.Report(quiet=True)
            cp.check_preprocessor_source(report)
        self.assertEqual([label for label, _ in report.failures], ['C preprocessor'])
        self.assertEqual(report.packages, ['base-devel'])

    def test_the_host_cpp_counts(self):
        def which(name):
            return '/usr/bin/cpp' if name == 'cpp' else None

        with mock.patch.object(cp.shutil, 'which', side_effect=which):
            report = cp.Report(quiet=True)
            cp.check_preprocessor_source(report)
        self.assertEqual(report.failures, [])


class RootBackedTest(unittest.TestCase):
    """Point the module at a scratch tree instead of the real checkout."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved_root = cp.ROOT
        cp.ROOT = self.root

    def tearDown(self):
        cp.ROOT = self.saved_root
        self.tmp.cleanup()

    def write(self, relative, data=b''):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path


class LegacyToolchainTest(RootBackedTest):
    REQUIRED = [
        'tools/legacy/bin/arm-elf-as',
        'tools/legacy/bin/arm-elf-ld',
        'tools/legacy/lib/libgcc.a',
        'tools/legacy/lib/libc.a',
    ]

    def test_complete_toolchain_is_ok(self):
        for name in self.REQUIRED:
            self.write(name)
        report = cp.Report(quiet=True)
        cp.check_legacy_toolchain(report)
        self.assertEqual(report.notes, [])
        self.assertEqual(report.failures, [])

    def test_a_partial_toolchain_names_what_is_missing(self):
        # The linker is the piece an older setup script never produced.
        for name in self.REQUIRED:
            if not name.endswith('arm-elf-ld'):
                self.write(name)
        report = cp.Report(quiet=True)
        cp.check_legacy_toolchain(report)
        self.assertEqual(len(report.failures), 1)
        self.assertIn('arm-elf-ld', report.failures[0][1])

    def test_binaries_without_their_libraries_fail_the_run(self):
        # What setup_legacy_toolchain.py leaves behind when the runtime-library
        # step fails: configure.py refuses this tree, so the checker must too.
        for name in self.REQUIRED:
            if '/bin/' in name:
                self.write(name)
        report = cp.Report(quiet=True)
        cp.check_legacy_toolchain(report)
        self.assertEqual([label for label, _ in report.failures], ['legacy toolchain'])
        self.assertIn('libgcc.a', report.failures[0][1])

    def test_an_absent_toolchain_fails_the_run(self):
        report = cp.Report(quiet=True)
        cp.check_legacy_toolchain(report)
        self.assertEqual(len(report.failures), 1)

    def test_a_non_executable_tool_fails_rather_than_passing_silently(self):
        # configure.py would die on it with a PermissionError traceback. 0644 is
        # not executable even for root, so this holds in CI's container too.
        self.write('tools/legacy/bin/arm-elf-as').chmod(0o644)
        report = cp.Report(quiet=True)
        cp.check_legacy_versions(report)
        self.assertEqual(len(report.failures), 1)
        self.assertIn('not executable', report.failures[0][1])


class RomTest(RootBackedTest):
    def test_matching_rom_is_ok(self):
        data = b'\x00' * 64
        digest = hashlib.sha1(data).hexdigest()
        self.write('roms/B8CE.gba', data)
        saved = cp.VERSIONS['us']
        cp.VERSIONS['us'] = ('B8CE', digest)
        try:
            report = cp.Report(quiet=True)
            cp.check_roms(report, ['us'])
            self.assertEqual(report.failures, [])
        finally:
            cp.VERSIONS['us'] = saved

    def test_mismatched_rom_is_a_failure(self):
        self.write('roms/B8CE.gba', b'not the game')
        report = cp.Report(quiet=True)
        cp.check_roms(report, ['us'])
        self.assertEqual(len(report.failures), 1)
        self.assertIn('sha1 mismatch', report.failures[0][1])

    def test_absent_rom_for_one_version_is_only_a_note(self):
        data = b'\x00' * 64
        self.write('roms/B8CE.gba', data)
        saved = cp.VERSIONS['us']
        cp.VERSIONS['us'] = ('B8CE', hashlib.sha1(data).hexdigest())
        try:
            report = cp.Report(quiet=True)
            cp.check_roms(report, ['us', 'jp'])
            self.assertEqual(report.failures, [])
            self.assertEqual(len(report.notes), 1)
        finally:
            cp.VERSIONS['us'] = saved

    def test_a_previous_matching_build_stands_in_for_the_dump(self):
        # tools/baserom.py falls back to build/<v>/verified.gba, and upstream's
        # own CI deletes roms/ and relies on it.
        data = b'\x00' * 64
        self.write('build/us/verified.gba', data)
        saved = cp.VERSIONS['us']
        cp.VERSIONS['us'] = ('B8CE', hashlib.sha1(data).hexdigest())
        try:
            report = cp.Report(quiet=True)
            cp.check_roms(report, ['us'])
            self.assertEqual(report.failures, [])
        finally:
            cp.VERSIONS['us'] = saved

    def test_the_dump_is_preferred_and_its_hash_is_final(self):
        # Like baserom.load: the first candidate that exists is the one used, so
        # a bad dump is an error even when a good verified.gba sits behind it.
        data = b'\x00' * 64
        self.write('roms/B8CE.gba', b'not the game')
        self.write('build/us/verified.gba', data)
        saved = cp.VERSIONS['us']
        cp.VERSIONS['us'] = ('B8CE', hashlib.sha1(data).hexdigest())
        try:
            report = cp.Report(quiet=True)
            cp.check_roms(report, ['us'])
            self.assertEqual([label for label, _ in report.failures], ['roms/B8CE.gba'])
        finally:
            cp.VERSIONS['us'] = saved

    def test_no_roms_at_all_is_a_failure(self):
        report = cp.Report(quiet=True)
        cp.check_roms(report, ['us', 'jp', 'eu'])
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0][0], 'base ROM')


class GbagfxTest(RootBackedTest):
    """gbagfx is required: extract_assets.py shells out to it for every
    tiles4/tiles8 and lz77 entry. Reporting it as optional let a tree pass
    every check and then fail on the next command the checker printed."""

    def build_gbagfx(self):
        path = self.write('tools/gbagfx/gbagfx', b'\x7fELF')
        path.chmod(0o755)
        return path

    def test_absent_gbagfx_is_a_failure(self):
        report = cp.Report(quiet=True)
        cp.check_gbagfx(report)
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0][0], 'gbagfx')
        self.assertIn('fetch_gbagfx.sh', report.failures[0][1])

    def test_present_gbagfx_is_ok(self):
        self.build_gbagfx()
        report = cp.Report(quiet=True)
        cp.check_gbagfx(report)
        self.assertEqual(report.failures, [])

    def test_a_built_gbagfx_needs_no_libraries(self):
        # libpng and zlib are only needed to compile it, so a tree that has the
        # binary must not be told to install anything - even on a host that
        # lacks them, which is what makes this test mean something on a host
        # that happens to have them.
        self.build_gbagfx()
        saved = cp.library_available
        cp.library_available = lambda package, header: False
        try:
            report = cp.Report(quiet=True)
            cp.check_gfx_libraries(report)
        finally:
            cp.library_available = saved
        self.assertEqual(report.failures, [])
        self.assertEqual(report.packages, [])

    def test_missing_libraries_name_their_arch_packages(self):
        saved = cp.library_available
        cp.library_available = lambda package, header: False
        try:
            report = cp.Report(quiet=True)
            cp.check_gfx_libraries(report)
        finally:
            cp.library_available = saved
        self.assertEqual(len(report.failures), 2)
        self.assertEqual(report.packages, ['libpng', 'zlib'])

    def test_present_libraries_are_ok(self):
        saved = cp.library_available
        cp.library_available = lambda package, header: True
        try:
            report = cp.Report(quiet=True)
            cp.check_gfx_libraries(report)
        finally:
            cp.library_available = saved
        self.assertEqual(report.failures, [])


class DistroTest(unittest.TestCase):
    ARCH_RELEASE = 'NAME="Arch Linux"\nID=arch\nID_LIKE=arch\n'
    ENDEAVOUR = 'NAME="EndeavourOS"\nID=endeavouros\nID_LIKE=arch\n'
    DEBIAN = 'NAME="Debian GNU/Linux"\nID=debian\n'

    def test_arch_is_arch(self):
        self.assertEqual(cp.detect_distro(self.ARCH_RELEASE), cp.ARCH)

    def test_an_arch_derivative_is_arch(self):
        # The hint is about the package manager, not the distribution's name.
        self.assertEqual(cp.detect_distro(self.ENDEAVOUR), cp.ARCH)

    def test_debian_is_generic(self):
        self.assertEqual(cp.detect_distro(self.DEBIAN), cp.GENERIC)

    def test_malformed_release_is_generic_rather_than_an_error(self):
        self.assertEqual(cp.detect_distro(''), cp.GENERIC)
        self.assertEqual(cp.detect_distro('nonsense\n\x00\xff'), cp.GENERIC)

    def test_quoted_id_is_unwrapped(self):
        self.assertEqual(cp.detect_distro('ID="arch"\n'), cp.ARCH)


class InstallHintTest(unittest.TestCase):
    def test_arch_gets_one_deduplicated_command(self):
        command = cp.install_command(
            ['arm-none-eabi-binutils', 'ninja', 'arm-none-eabi-binutils'], cp.ARCH
        )
        self.assertEqual(command, 'sudo pacman -S --needed arm-none-eabi-binutils ninja')

    def test_no_packages_means_no_command(self):
        self.assertIsNone(cp.install_command([], cp.ARCH))

    def test_other_distros_get_no_invented_package_names(self):
        # Nothing here knows an apt or dnf name, and a plausible-looking wrong
        # one is worse than saying nothing.
        self.assertIsNone(cp.install_command(['arm-none-eabi-binutils'], cp.GENERIC))


class VersionTableTest(RootBackedTest):
    def test_the_table_is_read_from_configure_py(self):
        self.write(
            'configure.py',
            b'DEFAULT_VERSION = "us"\n'
            b'VERSIONS = {\n'
            b'    "us": ("AAAA", "aa"),\n'
            b'    "xx": ("BBBB", "bb"),\n'
            b'}\n',
        )
        self.assertEqual(cp.load_versions(self.root), {'us': ('AAAA', 'aa'), 'xx': ('BBBB', 'bb')})

    def test_a_missing_configure_py_falls_back(self):
        self.assertEqual(cp.load_versions(self.root), cp.FALLBACK_VERSIONS)

    def test_an_unparsable_table_falls_back(self):
        self.write('configure.py', b'VERSIONS = build_it()\n')
        self.assertEqual(cp.load_versions(self.root), cp.FALLBACK_VERSIONS)

    def test_the_real_tree_agrees_with_the_fallback(self):
        # If this fails upstream changed the versions and the copy above is stale.
        self.assertEqual(cp.load_versions(), cp.FALLBACK_VERSIONS)


@unittest.skipIf(
    shutil.which('arm-none-eabi-cpp'),
    'a real cross preprocessor is installed, so the shim branch cannot be reached',
)
class PreprocessorShimTest(RootBackedTest):
    """The regression test for the bug the old docs encoded.

    `CPP=cpp` was documented as a substitute for arm-none-eabi-cpp. It is not:
    configure.py bakes the literal name into build.ninja, so the shim has to be
    on PATH at build time, not merely during bootstrap.
    """

    def setUp(self):
        super().setUp()
        self.saved = os.environ.pop('CPP', None)

    def tearDown(self):
        os.environ.pop('CPP', None)
        if self.saved is not None:
            os.environ['CPP'] = self.saved
        super().tearDown()

    def test_a_present_shim_is_a_note_that_names_the_build_wrapper(self):
        shim = self.write('build/shim/arm-none-eabi-cpp', b'#!/bin/sh\nexec cpp "$@"\n')
        shim.chmod(0o755)
        report = cp.Report(quiet=True)
        cp.check_preprocessor(report)

        self.assertEqual(report.failures, [], 'a buildable tree must not fail')
        self.assertEqual(len(report.notes), 1)
        detail = report.notes[0][1]
        self.assertIn('tools/build.sh', detail)
        self.assertIn('CPP=cpp', detail)
        self.assertIn('ninja', detail)

    def test_no_shim_and_no_cross_cpp_is_a_failure(self):
        report = cp.Report(quiet=True)
        cp.check_preprocessor(report)
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0][0], 'arm-none-eabi-cpp')

    def test_a_cpp_override_is_not_a_substitute(self):
        # The old docs' advice, at the checker level: CPP=cpp with neither the
        # cross cpp nor the shim once reported ready, and ninja then failed.
        os.environ['CPP'] = 'cpp'
        report = cp.Report(quiet=True)
        cp.check_preprocessor(report)
        self.assertEqual([label for label, _ in report.failures], ['arm-none-eabi-cpp'])
        self.assertTrue(any(label == 'CPP=cpp' for label, _ in report.notes))


class PythonPackageTest(RootBackedTest):
    """Packages live in .venv, so the running interpreter is the wrong oracle."""

    FAKE = (
        b'#!/bin/sh\n'
        b'# $1 is -c, $2 is "import <module>"\n'
        b'case "$2" in\n'
        b'  *mapfile_parser*) exit 0 ;;\n'
        b'  *) exit 1 ;;\n'
        b'esac\n'
    )

    def install_fake_venv(self):
        python = self.write('.venv/bin/python3', self.FAKE)
        python.chmod(0o755)
        return python

    def test_the_venv_interpreter_is_the_one_probed(self):
        self.install_fake_venv()
        report = cp.Report(quiet=True)
        cp.check_python_packages(report)

        failed = [label for label, _ in report.failures]
        self.assertEqual(failed, ['yaml', 'decomp_settings'])
        self.assertNotIn('mapfile_parser', failed)

    def test_a_missing_package_points_at_the_venv_not_at_pip(self):
        self.install_fake_venv()
        report = cp.Report(quiet=True)
        cp.check_python_packages(report)
        self.assertIn('.venv', report.failures[0][1])

    def test_no_venv_is_a_failure(self):
        # The next documented commands run from .venv, so a tree without one is
        # not ready - reporting it as a note once let such a tree exit 0.
        report = cp.Report(quiet=True)
        cp.check_python_packages(report)
        self.assertEqual([label for label, _ in report.failures], ['.venv'])
        self.assertIn('bootstrap', report.failures[0][1])


class CommandLineTest(unittest.TestCase):
    """Run the real CLI: argument handling cannot be checked by importing.

    Combining nargs='*' with choices= makes argparse validate the default on
    some interpreters, so passing no versions failed on one Python and worked on
    another. These run the script the way a person and CI both do.
    """

    SCRIPT = str(Path(cp.__file__).resolve())

    def run_cli(self, *args):
        import subprocess
        import sys
        return subprocess.run(
            [sys.executable, self.SCRIPT, *args],
            capture_output=True,
            text=True,
        )

    def test_no_arguments_is_accepted(self):
        result = self.run_cli('-q')
        self.assertNotIn('invalid choice', result.stderr)
        self.assertNotIn('usage:', result.stderr)

    def test_explicit_versions_are_accepted(self):
        result = self.run_cli('us', 'jp', '-q')
        self.assertNotIn('invalid', result.stderr)
        self.assertNotIn('usage:', result.stderr)

    def test_unknown_version_is_rejected(self):
        result = self.run_cli('bogus')
        self.assertEqual(result.returncode, 2)
        self.assertIn('invalid version', result.stderr)

    def test_help_lists_the_real_versions(self):
        result = self.run_cli('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('{eu,jp,us}', result.stdout)
        self.assertNotIn('[]', result.stdout)


if __name__ == '__main__':
    unittest.main()
