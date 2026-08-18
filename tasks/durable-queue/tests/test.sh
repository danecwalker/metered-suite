#!/bin/sh
# Grade a git patch in a pristine checkout. No network.
set -eu
cd /workspace
mkdir -p /out
: > /out/unittest.log

echo "verifier apply patch"
if [ -f /in/changes.patch ] && [ -s /in/changes.patch ]; then
  if ! git apply --whitespace=nowarn /in/changes.patch >> /out/unittest.log 2>&1; then
    echo "verifier apply failed"
    cat /out/unittest.log
    printf '%s\n' '{"ok":false,"reward":0,"failed":1,"error":"git apply failed"}' > /out/reward.json
    exit 0
  fi
else
  echo "verifier empty patch (starter)"
fi

export PYTHONPATH=/workspace
echo "verifier hidden tests"
set +e
python3 -m unittest discover -s /hidden-tests -v > /tmp/unittest.out 2>&1
status=$?
set -e
cat /tmp/unittest.out
cat /tmp/unittest.out >> /out/unittest.log
python3 -c '
import json, pathlib, re, sys
status = int(sys.argv[1])
log = pathlib.Path("/out/unittest.log").read_text(encoding="utf-8", errors="replace")
unit = re.findall(r"^(\S+) \([^)]+\) \.\.\. (ok|FAIL|ERROR|skipped)", log, re.M)
passed = [name for name, state in unit if state == "ok"]
failed = [name for name, state in unit if state in {"FAIL", "ERROR"}]
if not failed:
    failed = re.findall(r"^(?:FAIL|ERROR): (\S+)", log, re.M)
details = re.findall(
    r"^(?:AssertionError|Error|TypeError|ValueError|AttributeError): .+$",
    log,
    re.M,
)
payload = {
    "ok": status == 0,
    "reward": 1 if status == 0 else 0,
    "failed": 0 if status == 0 else max(1, len(failed) or 1),
    "passedTests": passed,
    "failedTests": failed,
}
if details:
    payload["details"] = details[:8]
if failed:
    payload["errors"] = failed[:12]
elif status != 0:
    payload["error"] = "hidden tests failed"
pathlib.Path("/out/reward.json").write_text(
    json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8"
)
' "$status"
exit 0
