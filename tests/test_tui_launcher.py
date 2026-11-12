import importlib.machinery
import types
import unittest
from unittest.mock import patch
import repo_tui_common as C


class TuiLauncher(unittest.TestCase):
    def test_missing_terminal_explains_install_without_seeding(self):
        module = types.ModuleType('tui_launcher')
        importlib.machinery.SourceFileLoader('tui_launcher', 'repo-tui').exec_module(module)
        with patch.object(C.shutil, 'which', return_value=None), patch.object(module, 'seed') as seed:
            with self.assertRaisesRegex(RuntimeError, 'brew install herdr'):
                module.launch()
            seed.assert_not_called()

    def test_terminal_search_includes_package_manager_paths(self):
        with patch.object(C.shutil, 'which', return_value='/opt/homebrew/bin/herdr') as which:
            self.assertEqual(C.tui_binary('/usr/bin:/bin'), '/opt/homebrew/bin/herdr')
            paths = which.call_args.kwargs['path'].split(':')
            self.assertIn('/opt/homebrew/bin', paths)
            self.assertIn('/usr/local/bin', paths)
            self.assertIn(str(C.Path.home()/'.local/bin'), paths)
