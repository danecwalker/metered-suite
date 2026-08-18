"""SKU helpers. Harness names and argv come from harness.yaml."""

from __future__ import annotations


def sku_fits(sku: str) -> bool:
    return bool((sku or "").strip())
