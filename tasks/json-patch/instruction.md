You are in a checkout of `jsonpatch`, a small RFC 6902 subset.

The public unit tests fail. Fix the library so this exits 0:

```
python3 -m unittest discover -s tests -v
```

Do not edit files under `tests/`. After you exit, a hidden verifier runs in a fresh container on a git patch of your work. Hardcoding the public fixtures will fail.

Required behavior:

- `apply(doc, ops)` applies a list of patch operations and returns the result. It must not mutate `doc`.
- Supported `op` values are `add`, `remove`, `replace`, and `test`. Other ops raise `PatchError`.
- `path` is a JSON Pointer. The empty path `""` is the whole document. Escape `~1` as `/` and `~0` as `~`, in that order.
- `add` inserts. For an object key it sets the value. For an array, `"-"` appends. A numeric token inserts at that index (existing items shift right). Parent must already exist.
- `remove` deletes the pointed value. The target must exist.
- `replace` overwrites a value that already exists.
- `test` compares the pointed value to `value` with Python `==`. A mismatch raises `PatchError`. A match leaves the document unchanged.
- Missing targets, bad pointers, and failed tests raise `PatchError`.

Run `python3 -m unittest discover -s tests -v` until those public tests pass. A hidden verifier then grades a git patch in a fresh container. Hidden cases use different documents and paths. Hardcoding the public fixtures will fail.
