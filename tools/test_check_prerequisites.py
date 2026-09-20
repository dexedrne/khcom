import hashlib
import os
import tempfile
import unittest
from pathlib import Path

import check_prerequisites as cp


class ReportTest(unittest.TestCase):
    def test_only_missing_entries_are_failures(self):
        report = cp.Report(quiet=True)
        report.ok('present')
        report.note('optional', 'not built yet')
        report.missing('absent', 'install it')
        self.assertEqual([label for label, _ in report.failures], ['absent'])
        self.assertEqual([label for label, _ in report.notes], ['optional'])


class PreprocessorTest(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.get('CPP')

    def tearDown(self):
        if self.saved is None:
            os.environ.pop('CPP', None)
        else:
            os.environ['CPP'] = self.saved

    def test_executable_override_is_accepted(self):
        os.environ['CPP'] = 'sh'
        report = cp.Report(quiet=True)
        cp.check_preprocessor(report)
        self.assertEqual(report.failures, [])

    def test_override_with_arguments_checks_only_the_program(self):
        os.environ['CPP'] = 'sh -c'
        report = cp.Report(quiet=True)
        cp.check_preprocessor(report)
        self.assertEqual(report.failures, [])

    def test_unusable_override_is_reported(self):
        os.environ['CPP'] = 'definitely-not-a-real-preprocessor'
        report = cp.Report(quiet=True)
        cp.check_preprocessor(report)
        self.assertEqual(len(report.failures), 1)


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
        self.assertEqual(len(report.notes), 1)
        self.assertIn('arm-elf-ld', report.notes[0][1])

    def test_an_incomplete_toolchain_never_fails_the_run(self):
        report = cp.Report(quiet=True)
        cp.check_legacy_toolchain(report)
        self.assertEqual(report.failures, [])


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

    def test_no_roms_at_all_is_a_failure(self):
        report = cp.Report(quiet=True)
        cp.check_roms(report, ['us', 'jp', 'eu'])
        self.assertEqual(len(report.failures), 1)
        self.assertEqual(report.failures[0][0], 'base ROM')


class GbagfxTest(RootBackedTest):
    def test_gbagfx_is_optional(self):
        report = cp.Report(quiet=True)
        cp.check_git_available_for_gbagfx(report)
        self.assertEqual(report.failures, [])
        self.assertEqual(len(report.notes), 1)


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
