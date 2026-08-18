# Edit this file. Do not edit tasks/ or metered_suite/.
# Display name, lab, and list prices come from Metered's catalog, not here.

HARNESS = "qwen"  # claude | chatgpt | gemini | grok | qwen | kimi | deepseek | opencode | pi
MODEL = "qwen3.8-max-preview"  # SKU the catalog already knows, unless you have high reputation
EFFORT = "max"
FLAGS = ["--yolo"]
MAX_ATTEMPTS = 0  # 0 = keep the same checkout until the hidden verifier passes
TIMEOUT_SEC = 45 * 60
