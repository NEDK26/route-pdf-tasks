#!/usr/bin/env python3
"""Unit checks for Markdown structural metrics."""

from __future__ import annotations

import json

from check_markdown_quality import markdown_table_metrics, without_fenced_code


def main() -> int:
    markdown = """\
# Heading

```text
fake        raw        layout
| not | a | table |
| --- | - | ----- |
```

| Key | Value |
|---|---|
| A | B |
| C | D |
"""
    structural = without_fenced_code(markdown)
    assert "fake        raw" not in structural
    assert markdown_table_metrics(structural) == (4, 1, 3, 1)
    print(json.dumps({"status": "passed", "fenced_code_ignored": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
