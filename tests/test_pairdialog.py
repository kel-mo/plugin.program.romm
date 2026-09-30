import unittest

import support  # noqa: F401

from resources.lib.pairdialog import PairDialog

ACTION_STOP = 13
ACTION_TELETEXT_GREEN = 216


class Action:
    def __init__(self, action_id):
        self.action_id = action_id

    def getId(self):
        return self.action_id


class Cancel(unittest.TestCase):
    def dialog(self, action_id):
        dialog = PairDialog.__new__(PairDialog)
        dialog.cancelled = False
        dialog.close = lambda: None
        dialog.onAction(Action(action_id))
        return dialog.cancelled

    def test_stop_cancels(self):
        self.assertTrue(self.dialog(ACTION_STOP))

    def test_teletext_green_ignored(self):
        self.assertFalse(self.dialog(ACTION_TELETEXT_GREEN))


if __name__ == '__main__':
    unittest.main()
