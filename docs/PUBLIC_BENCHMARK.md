# Public Benchmark

Rta-Smriti ships a small synthetic benchmark as package data so source checkouts,
clean wheels, and standalone artifacts can run the same privacy-safe regression.

```bash
rta-brain benchmark --json
```

The corpus contains no private repositories, user paths, generated context packs,
or production memories. Its SHA-256 digest appears in every result.

## Measures

- nDCG, recall, reciprocal rank, and precision at the fixed retrieval limit
- relevant-result share as a simple context-efficiency signal
- p50 and p95 local query latency
- stale-source rejection
- simple contradiction detection
- structured continuation success
- governance allow/block accuracy

The default run compares `no_memory`, lexical FTS5, and dependency-free
hash-hybrid retrieval. It also emits an `optional_semantic` record with
`status: not_requested`, so omitted optional evidence cannot be mistaken for a
completed comparison.

To include an explicitly selected Sentence Transformers model:

```bash
rta-brain benchmark --include-semantic --semantic-model all-MiniLM-L6-v2 --json
```

This mode requires the `embeddings` extra and an available model. If the optional
provider or model cannot initialize, the benchmark reports `status: unavailable`
without failing the required dependency-free modes or exposing the underlying
machine error. Enabling it is explicit because first-time model initialization
may require a network download by Sentence Transformers.

## Interpretation

This corpus is deliberately small and transparent. A perfect relevance score can
mean the task is easy, not that one retrieval method is universally superior.
Latency varies by machine, and context efficiency exposes when a method returns
more non-relevant material. Use the benchmark to catch regressions and reproduce
behavior, not as independent proof that Rta-Smriti outperforms another product.

Release CI stores the JSON result from Ubuntu/Python 3.11 as an artifact while
also running the same benchmark on Windows, macOS, and supported Python versions.
Required CI remains dependency-free and does not request the optional model.
