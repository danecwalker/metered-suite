# Edit this file. Do not edit tasks/ or metered_suite/.
# Those files are the official jobs. Changing them invalidates the package.

HARNESS = "claude"
MODEL = "claude-opus-4-6"
EFFORT = "high"

# How your harness is invoked. {prompt} is the official instruction.
# Add flags your tool needs: --dangerously-skip-permissions, --yolo, etc.
COMMAND = [
    "claude",
    "-p",
    "--model",
    MODEL,
    "--dangerously-skip-permissions",
    "{prompt}",
]

MODEL_NAME = "Claude Opus 4.6"
LAB = "Anthropic"
PROVIDER = "Anthropic"
SKU = "claude-opus-4-6"
LIST_INPUT = 15
LIST_OUTPUT = 75

# Optional. If the harness writes usage.json in the task workspace, that wins.
# Otherwise totals stay 0 and the row cannot get a $ / M ET.
MAX_ATTEMPTS = 3
