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

    def test_browsing_and_tier_previews_never_grant_download_access(self):
        ui = self.ui
        tools = [dict(name=name, membership=code, type1=kind, slug=name.lower())
                 for name,code,kind in (("Basic","free","audio"),("Voice","pd","audio"),
                                        ("Studio","fh","video"),("Shop","fs","video"))]
        def visible():
            return {ui.results.item(i).text() for i in range(ui.results.count())}
        def choose(tier):
            ui.membership.setCurrentIndex(ui.membership.findData(tier))
        with patch("app_search.catalog", return_value=(tools,False)):
            ui.refresh.click();self.idle()
            everyone={"Basic","Voice","Studio","Shop"}
            self.assertEqual(visible(),everyone)
            choose("farm-hand")
            self.assertEqual(visible(),{"Basic","Voice","Studio"})
            self.assertFalse(ui.get.isEnabled())
            choose("mine")
            self.assertFalse(visible())
            self.assertIn("Sign in",ui.details.text())
            user=self.approved(ui.auth.generate_token())
            with patch.object(ui.auth,"load_cache"), patch.object(ui.auth,"cached_auth",dict(user,tier="free")):
                ui.update_auth()
                self.assertEqual(visible(),{"Basic"})
                choose("")
                self.assertEqual(visible(),everyone)
                choose("farm-hand")
                ui.search.setText("Studio")
                self.assertEqual(visible(),{"Studio"})
                self.assertFalse(ui.get.isEnabled())
                with patch.object(ui,"job") as submit:
                    ui.download()
                    submit.assert_not_called()
                ui.search.clear()
                choose("mine")
                ui.auth.cached_auth=user
                ui.update_auth()
                self.assertEqual(visible(),{"Basic","Voice"})
                ui.auth.cached_auth=dict(user,tier="farm-hand")
                ui.update_auth()
                self.assertEqual(visible(),{"Basic","Voice","Studio"})
                ui.type.setCurrentIndex(ui.type.findData("video"))
                ui.search.setText("Studio")
                with patch.object(ui.auth,"verify_link",return_value=ui.auth.cached_auth), patch.object(ui.auth,"save_cache"):
                    ui.refresh.click();self.idle()
                self.assertEqual(visible(),{"Studio"})
                self.assertTrue(ui.get.isEnabled())
                ui.auth.cached_auth=None
                ui.update_auth()
                self.assertEqual(ui.membership.currentData(),"")
                self.assertFalse(ui.get.isEnabled())
            ui.search.clear()
            ui.type.setCurrentIndex(0)
            choose("prairie-dog"); self.assertEqual(visible(),{"Basic","Voice"})
            choose("free"); self.assertEqual(visible(),{"Basic"})

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
