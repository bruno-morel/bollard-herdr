import contextlib
import io
import unittest
from unittest.mock import patch
import install_dependencies as D


class Dependencies(unittest.TestCase):
    def rows(self, profile):
        with patch.object(D.shutil, "which", return_value=None):
            return D.inspect(profile)

    def test_profiles_require_hc_and_only_selected_interface(self):
        desktop = {n for n, _, required, _ in self.rows("desktop") if required}
        tui = {n for n, _, required, _ in self.rows("jumpbox") if required}
        both = {n for n, _, required, _ in self.rows("laptop") if required}
        self.assertIn("hc", desktop & tui & both)
        self.assertIn("herdr-app", desktop)
        self.assertNotIn("herdr", desktop)
        self.assertIn("herdr", tui)
        self.assertNotIn("herdr-app", tui)
        self.assertTrue({"herdr", "herdr-app"} <= both)
        self.assertNotIn("docker", both)

    def test_reports_all_missing_requirements_and_core_command(self):
        output = io.StringIO()
        with patch.object(
            D.shutil, "which", return_value=None
        ), contextlib.redirect_stdout(output):
            self.assertFalse(D.check("all"))
        text = output.getvalue()
        self.assertIn("[MISSING] hc", text)
        self.assertIn("[MISSING] herdr-app", text)
        self.assertIn("[MISSING] herdr ", text)
        self.assertIn("https://releases.herdr.dev/core/install.sh", text)

    def test_installed_but_not_on_path_is_explained(self):
        def which(name, path):
            return "/opt/homebrew/bin/" + name if "/opt/homebrew/bin" in path else None

        with patch.dict(D.os.environ, PATH="/usr/bin"), patch.object(
            D.shutil, "which", side_effect=which
        ), patch.object(D.subprocess, "run") as run:
            run.return_value.returncode = 0
            rows = D.inspect("tui")
        hc = next(r for r in rows if r[0] == "hc")
        self.assertFalse(hc[1])
        self.assertIn("add its directory to PATH", hc[3])
