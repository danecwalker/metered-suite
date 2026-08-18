import unittest

from jsonpatch import PatchError, apply


class PublicPatchTests(unittest.TestCase):
    def test_replace_object_key(self) -> None:
        out = apply({"a": 1}, [{"op": "replace", "path": "/a", "value": 2}])
        self.assertEqual(out, {"a": 2})

    def test_add_and_remove(self) -> None:
        out = apply({"a": 1}, [{"op": "add", "path": "/b", "value": 3}])
        self.assertEqual(out["b"], 3)
        out = apply(out, [{"op": "remove", "path": "/a"}])
        self.assertEqual(out, {"b": 3})

    def test_does_not_mutate_input(self) -> None:
        src = {"a": 1}
        apply(src, [{"op": "replace", "path": "/a", "value": 9}])
        self.assertEqual(src, {"a": 1})

    def test_test_op_accepts_and_rejects(self) -> None:
        apply({"a": 1}, [{"op": "test", "path": "/a", "value": 1}])
        with self.assertRaises(PatchError):
            apply({"a": 1}, [{"op": "test", "path": "/a", "value": 2}])

    def test_array_append(self) -> None:
        out = apply({"xs": [1]}, [{"op": "add", "path": "/xs/-", "value": 2}])
        self.assertEqual(out["xs"], [1, 2])

    def test_replace_missing_raises(self) -> None:
        with self.assertRaises(PatchError):
            apply({}, [{"op": "replace", "path": "/nope", "value": 1}])


if __name__ == "__main__":
    unittest.main()
