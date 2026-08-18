# Edit this file. Do not edit tasks/ or metered_suite/.
# Display name, lab, and list prices come from Metered's catalog, not here.

HARNESS = "qwen"  # claude | chatgpt | gemini | grok | qwen | kimi | deepseek | opencode | pi
MODEL = "qwen3.8-max-preview"  # SKU the catalog already knows, unless you have high reputation
EFFORT = "max"
FLAGS = ["--yolo"]
MAX_ATTEMPTS = 3
TIMEOUT_SEC = 45 * 60
