#!/usr/bin/env python3
"""Deterministic unit checks for content-free PDF probe helpers."""

from __future__ import annotations

import json

from probe_pdf import aligned_clusters, image_metrics, parse_page_areas


def main() -> int:
    box_output = """\
Page    1 size:  100 x 100 pts
Page    2 size:  200 x 100 pts
"""
    sizes = parse_page_areas(box_output, 2)
    assert sizes == [(100.0, 100.0), (200.0, 100.0)]

    image_output = """\
   1     0 image     100   100  rgb     3   8  image  no         1  0    72    72  1B  1%
   2     1 image     100   100  rgb     3   8  image  no         2  0    72    72  1B  1%
"""
    metrics = image_metrics(image_output, sizes)
    assert metrics[0]["aggregate_area_ratio"] == 1.0
    assert metrics[1]["aggregate_area_ratio"] == 0.5
    assert aligned_clusters({2: 4, 3: 2, 40: 6}, 6) == 2

    print(json.dumps({"status": "passed", "mixed_page_sizes": sizes}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
