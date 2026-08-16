# Performance Evidence

Rta-Smriti ships a bounded synthetic scale probe so performance claims can be reproduced without
publishing private repository data.

## Method

The probe generates deterministic Python files, uses the regex parser and local hash-hybrid
retrieval, and measures:

- initial atomic indexing;
- deep SHA-256 freshness;
- cold-start plus 30-sample steady-state hybrid retrieval median and p95 latency;
- cold-start plus 15-sample steady-state bounded context-pack median and p95 latency;
- SQLite size and peak traced Python allocation.

Run the release-scale profile:

```bash
python scripts/performance_probe.py --profiles 100 1000 10000 --assert-bounds
```

CI runs the 100 and 1,000-file profiles. The 10,000-file profile is a release benchmark because
allocation tracing and synthetic file creation make it intentionally slower.

## Current Local Baseline

The committed [machine-readable baseline](../benchmarks/performance-baseline-v1.json) was produced
on Windows, AMD64, Python 3.13.7. It is evidence for this environment, not a universal speed claim.

| Files | Index | Deep Freshness | Search p95 | Context Pack p95 | Brain Size | Peak Traced Allocation |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 100 | 2.068 s | 0.012 s | 5.035 ms | 7.569 ms | 0.64 MB | 0.89 MB |
| 1,000 | 19.405 s | 0.118 s | 49.496 ms | 51.877 ms | 4.15 MB | 1.87 MB |
| 10,000 | 198.619 s | 1.158 s | 238.927 ms | 243.236 ms | 39.31 MB | 20.63 MB |

Indexing stayed near 20 seconds per 1,000 synthetic files in this traced run. Each profile records
a separate cold observation plus 30 steady-state retrieval and 15 steady-state context-pack samples.
Context packs remained under 2.4 KB for the fixed 2,000-token budget. Real repositories vary with
file size, parser choice, filesystem, antivirus, optional embeddings, and Git configuration.

## Regression Bounds

`--assert-bounds` is deliberately generous: 60 seconds per 1,000 files, 1,000 ms p95 retrieval,
1,500 ms p95 context generation, and 32 KB maximum pack output. These are pathological-regression
guards, not product latency promises.
