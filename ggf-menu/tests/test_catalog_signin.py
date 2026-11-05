"""Drive the real catalog controls and Qt workers with an isolated Windows profile."""
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from app_search import SearchDialog


class SigninTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["catalog-qa", "-platform", "offscreen"])

    def setUp(self):
        profile = tempfile.TemporaryDirectory()
        self.addCleanup(profile.cleanup)
        for p in [patch.dict(os.environ, LOCALAPPDATA=profile.name),
                  patch("app_search.catalog", return_value=([dict(name="Member tool", membership="pd", slug="tool")], False))]:
            p.start()
            self.addCleanup(p.stop)
        self.ui = SearchDialog()
        self.addCleanup(self.ui.close)
        self.idle()

    def idle(self):
        deadline = time.monotonic() + 5
        while True:
            QTest.qWait(10)
            if not self.ui.jobs:
                return
            if time.monotonic() > deadline:
                self.fail("Catalog worker did not finish")

    @staticmethod
    def approved(token):
        return dict(name="QA", tier="prairie-dog", expires=int(time.time())+3600, token=token)

    def test_signed_out_browser_resume_and_refresh_after_explicit_approval(self):
        ui = self.ui
        with patch("webbrowser.open", return_value=True) as browser, patch.object(ui.auth, "verify_link", return_value=None) as verify:
            ui.link.click()
            self.idle()
            url, code = browser.call_args.args[0], ui.member.text()
            self.assertTrue(ui.link.isEnabled() and not ui.stop_link.isHidden())
            self.assertEqual(ui.link.text(), "Continue in browser")
            self.assertIn(code.split()[-1].lower(), url)
            # A website session by itself is not an approved desktop link.
            ui.refresh.click()
            self.idle()
            self.assertFalse(ui.get.isEnabled())
            self.assertIn("Link Desktop App", ui.link_hint.text())
            ui.link.click()
            self.idle()
            self.assertEqual(browser.call_args.args[0], url)
            self.assertEqual(ui.member.text(), code)
            verify.side_effect = self.approved
            ui.refresh.click()
            self.idle()
            self.assertEqual(ui.link.text(), "Sign out")
            self.assertEqual(ui.member.text(), "Prairie Dog")
            self.assertTrue(ui.get.isEnabled())
            self.assertTrue(ui.stop_link.isHidden())

    def test_cancel_ignores_late_approval_even_after_restart(self):
        gate = threading.Event()
        ui = self.ui
        seen = []
        def delayed(token):
            seen.append(token)
            if len(seen) == 1:
                gate.wait(3)
                return self.approved(token)
            return None
        with patch("webbrowser.open", return_value=True), patch.object(ui.auth, "verify_link", side_effect=delayed):
            ui.link.click()
            first = ui.pending_token
            ui.stop_link.click()
            self.assertEqual(ui.link.text(), "Sign in")
            ui.link.click()
            second = ui.pending_token
            gate.set()
            self.idle()
            self.assertNotEqual(first, second)
            self.assertEqual(seen, [first, second])
            self.assertFalse(ui.auth.get_auth() or ui.get.isEnabled())
            self.assertEqual(ui.link.text(), "Continue in browser")
            ui.link_deadline = 0
            ui.refresh.click()
            self.idle()
            self.assertEqual(ui.link.text(), "Sign in")
            self.assertIn("timed out", ui.link_hint.text())

    def test_browser_failure_network_and_cache_recovery(self):
        ui = self.ui
        with patch("webbrowser.open", return_value=False), patch.object(ui.auth, "verify_link", return_value=None) as verify:
            ui.link.click()
            self.idle()
            self.assertIn("browser did not open", ui.link_hint.text())
            verify.side_effect = ConnectionError("Offline.")
            ui.refresh.click()
            self.idle()
            self.assertIn("Offline.", ui.link_hint.text())
            self.assertTrue(ui.link.isEnabled() and ui.stop_link.isEnabled())
            verify.side_effect = self.approved
            with patch.object(ui.auth, "save_cache", side_effect=OSError("disk full")):
                ui.refresh.click()
                self.idle()
            self.assertFalse(ui.get.isEnabled())
            self.assertIn("could not save", ui.link_hint.text())
            ui.link_timer.start(1)
            deadline = time.monotonic() + 3
            while ui.pending_token and time.monotonic() < deadline:
                QTest.qWait(20)
            self.idle()
            self.assertTrue(ui.get.isEnabled())
            # A network failure is different from a revoked desktop credential.
            verify.side_effect = ConnectionError("Offline.")
            ui.refresh.click()
            self.idle()
            self.assertEqual(ui.link.text(), "Sign out")
            verify.side_effect = None
            ui.refresh.click()
            self.idle()
            self.assertEqual(ui.link.text(), "Sign in")
            self.assertFalse(ui.get.isEnabled())
