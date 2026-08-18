#!/bin/sh
# Grade a git patch in a pristine checkout. No network.
set -eu
cd /workspace
mkdir -p /out
: > /out/unittest.log

if [ -f /in/changes.patch ] && [ -s /in/changes.patch ]; then
  if ! git apply --whitespace=nowarn /in/changes.patch >> /out/unittest.log 2>&1; then
    printf '%s\n' '{"ok":false,"reward":0,"failed":1,"error":"git apply failed"}' > /out/reward.json
    exit 0
  fi
fi

export PYTHONPATH=/workspace
set +e
python3 -m unittest discover -s /hidden-tests -v >> /out/unittest.log 2>&1
status=$?
set -e
python3 -c '
import json, pathlib, re, sys
status = int(sys.argv[1])
log = pathlib.Path("/out/unittest.log").read_text(encoding="utf-8", errors="replace")
fails = re.findall(r"^(?:FAIL|ERROR): (\S+)", log, re.M)
payload = {
    "ok": status == 0,
    "reward": 1 if status == 0 else 0,
    "failed": 0 if status == 0 else max(1, len(fails) or 1),
}
if fails:
    payload["errors"] = fails[:12]
elif status != 0:
    payload["error"] = "hidden tests failed"
pathlib.Path("/out/reward.json").write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
' "$status"
exit 0
