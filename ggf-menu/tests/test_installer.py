import os
import tempfile
import unittest
import zipfile

from ggf_installer import (
    InstallSafetyError,
    discover_install_files,
    load_registry,
    safe_extract_zip,
    safe_install_path,
    sanitize_folder_name,
    upsert_registry,
    validate_delete_target,
    write_install_marker,
)


class InstallerSafetyTests(unittest.TestCase):
    def test_folder_name_is_single_safe_component(self):
        self.assertEqual(sanitize_folder_name(r"..\Bad: App"), "-Bad- App")
        with self.assertRaises(InstallSafetyError):
            sanitize_folder_name("CON")

    def test_install_path_cannot_escape_base(self):
        with tempfile.TemporaryDirectory() as base:
            target = safe_install_path(base, r"..\outside")
            self.assertEqual(os.path.commonpath([base, target]), base)

    def test_zip_slip_is_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = os.path.join(temp, "bad.zip")
            destination = os.path.join(temp, "out")
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("good.txt", "good")
                handle.writestr("../escaped.txt", "bad")
            with self.assertRaises(InstallSafetyError):
                safe_extract_zip(archive, destination)
            self.assertFalse(os.path.exists(os.path.join(temp, "escaped.txt")))
            self.assertFalse(os.path.exists(os.path.join(destination, "good.txt")))

    def test_good_zip_and_exact_install_launcher_are_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = os.path.join(temp, "app.zip")
            destination = os.path.join(temp, "out")
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("install.bat", "@echo off")
                handle.writestr("run.bat", "@echo off")
            count, size = safe_extract_zip(archive, destination)
            found = discover_install_files(destination)
            self.assertEqual(count, 2)
            self.assertGreater(size, 0)
            self.assertEqual(os.path.basename(found["best_installer"]), "install.bat")
            self.assertEqual(os.path.basename(found["best_launcher"]), "run.bat")

    def test_registry_upsert_deduplicates_name_and_path(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = os.path.join(temp, "installed_apps.txt")
            first = os.path.join(temp, "one", "app")
            second = os.path.join(temp, "two", "app")
            upsert_registry(registry, "Example", first)
            upsert_registry(registry, "example", second)
            self.assertEqual(load_registry(registry), {"example": (os.path.abspath(second), None)})

    def test_delete_requires_deep_non_protected_target(self):
        with tempfile.TemporaryDirectory() as temp:
            app_dir = os.path.join(temp, "tray", "program")
            install = os.path.join(temp, "apps", "vendor", "tool")
            os.makedirs(app_dir)
            os.makedirs(install)
            ok, _reason, marked = validate_delete_target(install, app_dir)
            self.assertTrue(ok)
            self.assertFalse(marked)
            write_install_marker(install, "Tool", "tool.zip", None)
            self.assertTrue(validate_delete_target(install, app_dir)[2])
            self.assertFalse(validate_delete_target(os.path.splitdrive(install)[0] + os.sep, app_dir)[0])


if __name__ == "__main__":
    unittest.main()
