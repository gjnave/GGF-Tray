import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from ggf_catalog_window import CatalogOwner, activate_existing
from ggf_startup import configure, paths
from ggf_welcome_state import welcome_seen, remember_welcome

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

