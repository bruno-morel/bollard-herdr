import unittest
from repo_herdr import conversation_choice

class ConversationMenu(unittest.TestCase):
    def test_provider_selection_does_not_launch(self):
        for provider in ('codex', 'claude', 'cursor'):
            self.assertEqual(conversation_choice(provider, 'codex'), ('agent', provider, ''))
        self.assertEqual(conversation_choice('', 'cursor'), ('menu', 'cursor', ''))

    def test_explicit_new_and_resume(self):
        self.assertEqual(conversation_choice('n', 'cursor'), ('new', 'cursor', ''))
        self.assertEqual(conversation_choice('new claude', 'cursor'), ('new', 'claude', ''))
        self.assertEqual(conversation_choice('resume', 'cursor'), ('resume', 'cursor', ''))
        self.assertEqual(conversation_choice('r saved-id', 'cursor'), ('resume', 'cursor', 'saved-id'))
        self.assertEqual(conversation_choice('new unknown', 'cursor')[0], 'invalid')
