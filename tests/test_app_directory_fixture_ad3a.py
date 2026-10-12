import os
import pathlib
import sys
import unittest
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent
for path in (str(ROOT), str(TESTS)):
    if path not in sys.path:
        sys.path.insert(0, path)

import managed_app_directory as directory
from app_directory_fixture import AppDirectoryFixture


@unittest.skipUnless(os.name == "nt", "Windows named mappings are required")
class AppDirectoryFixtureContract(unittest.TestCase):
    def setUp(self):
        self.pid = 910000 + (os.getpid() % 80000)
        self.instance = uuid.uuid4().hex
        self.fixture = AppDirectoryFixture(self.pid, self.instance)
        self.reader = directory.DirectoryReader(self.pid)

    def tearDown(self):
        self.reader.close()
        self.fixture.close()

    def reopen(self):
        self.reader.close()
        self.reader = directory.DirectoryReader(self.pid)
        self.assertTrue(self.reader.open(), self.reader.open_failure)
        return self.reader.last

    def test_complete_lifecycle_matches_the_product_reader(self):
        snap = self.reopen()
        self.assertEqual((snap.instance, snap.app_pid, snap.flags), (self.instance, 0, directory.FLAG_INSTANCE_PUBLISHED))
        self.fixture.publish_process_started(os.getpid())
        snap = self.reader.poll()
        self.assertEqual((snap.app_pid, snap.process_started, snap.usable), (os.getpid(), True, False))
        self.fixture.publish_ready_accepted()
        snap = self.reader.poll()
        self.assertTrue(snap.ready_accepted)
        self.assertTrue(snap.usable)
        self.fixture.publish_withdrawing()
        snap = self.reader.poll()
        self.assertTrue(snap.withdrawing)
        self.assertFalse(snap.usable)
        self.fixture.publish_closed()
        snap = self.reader.poll()
        self.assertTrue(snap.closed)
        self.assertEqual((snap.instance, snap.app_pid, snap.flags), ("", 0, directory.FLAG_CLOSED))

    def test_close_is_idempotent_and_removes_the_mapping_name(self):
        self.assertTrue(self.reader.open())
        self.fixture.close()
        self.fixture.close()
        self.reader.close()
        probe = directory.DirectoryReader(self.pid)
        try:
            self.assertFalse(probe.open())
            self.assertEqual(probe.open_failure, "block-missing")
        finally:
            probe.close()

    def test_zero_one_and_many_fixtures_are_pid_isolated(self):
        self.fixture.close()
        self.reader.close()
        fixtures = []
        readers = []
        try:
            for offset in range(12):
                pid = self.pid + offset
                inst = uuid.uuid4().hex
                writer = AppDirectoryFixture(pid, inst)
                writer.publish_process_started(os.getpid())
                fixtures.append(writer)
                reader = directory.DirectoryReader(pid)
                self.assertTrue(reader.open())
                readers.append(reader)
                self.assertEqual((reader.last.bve_pid, reader.last.instance, reader.last.app_pid), (pid, inst, os.getpid()))
            fixtures[5].publish_ready_accepted()
            self.assertTrue(readers[5].poll().usable)
            for index, reader in enumerate(readers):
                if index != 5:
                    self.assertFalse(reader.poll().usable)
        finally:
            for reader in readers:
                reader.close()
            for writer in fixtures:
                writer.close()

    def test_invalid_transitions_fail_before_writing(self):
        with self.assertRaises(RuntimeError):
            self.fixture.publish_ready_accepted()
        with self.assertRaises(ValueError):
            self.fixture.publish_process_started(0)
        snap = self.reopen()
        self.assertEqual((snap.flags, snap.app_pid), (directory.FLAG_INSTANCE_PUBLISHED, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
