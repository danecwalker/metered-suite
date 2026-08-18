from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from metered_suite.term import color_enabled, green, paint


class TermTests(unittest.TestCase):
    def test_no_color_env_strips_paint(self) -> None:
        with patch.dict(os.environ, {"NO_COLOR": "1"}, clear=False):
            self.assertFalse(color_enabled())
            self.assertEqual(green("ok"), "ok")
            self.assertEqual(paint("ok", "\033[32m"), "ok")


if __name__ == "__main__":
    unittest.main()
