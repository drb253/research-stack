# Caching for the API

The cache is a useful engineering tradeoff. It cut median latency by 42% in our tests.
The error rate did not move; it stayed at about 3.1 errors per 1000 requests. A larger
replication at 180 requests per second confirmed the same shape.

The cache is not a substitute for fixing the query plan.

## What changed
- §1 binary contrast: "isn't a silver bullet. It is a useful tradeoff" is now one plain sentence.
- §3 throat-clearing: dropped the opening "It's worth noting that".
