import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from ggf_catalog_window import CatalogOwner, activate_existing, ready_for_catalog_upgrade
from ggf_startup import configure, paths
from ggf_welcome_state import welcome_seen, remember_welcome, managed_install, tray_notice_marker

class TrayLifecycleTests(unittest.TestCase):
    def setUp(self):
        profile=tempfile.TemporaryDirectory()
        self.addCleanup(profile.cleanup)
        self.base=Path(profile.name)
        env=patch.dict(os.environ, {"LOCALAPPDATA":str(self.base/"Local"), "APPDATA":str(self.base/"Roaming")})
        env.start()
        self.addCleanup(env.stop)

    def test_catalog_election_activation_and_reopen(self):
        first=CatalogOwner()
        second=CatalogOwner()
        try:
            self.assertTrue(first.primary)
            self.assertFalse(second.primary)
            self.assertTrue(activate_existing(welcome=True))
            self.assertEqual(first.consume(), (True,True))
            self.assertEqual(first.consume(), (False,False))
        finally:
            second.release()
            first.release()
        new=CatalogOwner()
        try: self.assertTrue(new.primary)
        finally: new.release()

    def test_catalog_surviving_its_tray_blocks_upgrade_until_closed(self):
        owner = CatalogOwner()
        try:
            self.assertFalse(ready_for_catalog_upgrade(interactive=False))
            with patch("ggf_catalog_window.user.MessageBoxW", return_value=2):
                self.assertFalse(ready_for_catalog_upgrade(interactive=True))
            self.assertEqual(owner.consume(), (False, False))
        finally:
            owner.release()
        self.assertTrue(ready_for_catalog_upgrade(interactive=False))

    def test_startup_opt_out_persists_and_can_be_reenabled(self):
        self.assertTrue(configure("install"))
        active,parked=paths()
        self.assertTrue(active.is_file())
        self.assertFalse(configure("off"))
        self.assertTrue(parked.is_file())
        self.assertFalse(configure("install"))
        self.assertFalse(configure("default"))
        self.assertTrue(configure("on"))
        self.assertFalse(parked.exists())

    def test_old_predisplay_flag_does_not_skip_welcome(self):
        state=self.base/"Local/GGF-Tray"
        state.mkdir(parents=True)
        (state/"tray_ui_state.json").write_text('{"intro_shown":true}')
        self.assertFalse(welcome_seen())
        (state/"visualizer_config.json").write_text('{"tourSeen":true}')
        self.assertTrue(welcome_seen())
        (state/"visualizer_config.json").write_text('{}')
        remember_welcome()
        self.assertTrue(welcome_seen())

    def test_portable_use_does_not_consume_install_notice_and_upgrade_does_not_repeat_it(self):
        programs = self.base / "Local/Programs/Get Going Fast"
        for folder, is_install, already_seen in (
            (self.base / "Downloads", False, False),
            (programs / "Tray-0.16.2", True, False),
            (programs / "Tray-0.17.0", True, True),
            (self.base / "Downloads/Tray-0.17.0", False, True),
        ):
            with self.subTest(folder=folder), patch("ggf_welcome_state.get_app_dir", return_value=folder):
                self.assertEqual(managed_install(), is_install)
                self.assertEqual(tray_notice_marker().exists(), already_seen)
                tray_notice_marker().touch()

