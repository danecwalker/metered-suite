"""Held-out verifier. Not copied into the agent workspace."""

from __future__ import annotations

import unittest

from jsonpatch import PatchError, apply


class HiddenPatchTests(unittest.TestCase):
    def test_pointer_escapes(self) -> None:
        src = {"a/b": {"~": 1}}
        out = apply(src, [{"op": "replace", "path": "/a~1b/~0", "value": 7}])
        self.assertEqual(out, {"a/b": {"~": 7}})
        self.assertEqual(src, {"a/b": {"~": 1}})

    def test_array_insert_shifts(self) -> None:
        out = apply({"xs": ["a", "c"]}, [{"op": "add", "path": "/xs/1", "value": "b"}])
        self.assertEqual(out["xs"], ["a", "b", "c"])

    def test_remove_array_index(self) -> None:
        out = apply({"xs": [1, 2, 3]}, [{"op": "remove", "path": "/xs/1"}])
        self.assertEqual(out["xs"], [1, 3])

    def test_empty_path_replaces_document(self) -> None:
        out = apply({"old": True}, [{"op": "replace", "path": "", "value": [1, 2]}])
        self.assertEqual(out, [1, 2])

    def test_add_missing_parent_raises(self) -> None:
        with self.assertRaises(PatchError):
            apply({}, [{"op": "add", "path": "/a/b", "value": 1}])

    def test_unsupported_op_raises(self) -> None:
        with self.assertRaises(PatchError):
            apply({"a": 1}, [{"op": "move", "from": "/a", "path": "/b"}])


if __name__ == "__main__":
    unittest.main()
