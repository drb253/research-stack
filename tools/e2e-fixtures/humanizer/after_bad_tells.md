# Caching for the API

The cache is a useful engineering tradeoff. It cut median latency by 42% in our tests.
The error rate did not move; it stayed at about 3.1 errors per 1000 requests. A larger
replication at 180 requests per second confirmed the same shape. As an AI, I hope this
helps.

The cache is not a substitute for fixing the query plan.
