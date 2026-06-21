# Changelog

## 0.1.0 — 2026-06-21
Initial release.

- Cost model: status-based tiered fees, native-token discounts (with carry),
  conditional market-maker programs, expected maker rate (fill probability +
  adverse selection), spread, convex participation impact, and trade-size
  (V/N) impact.
- MILP allocator (CBC via PuLP) with a local-search fallback; respects
  counterparty caps and regional venue access.
- Rolling-30-day tier-sprint breakeven.
- Six indicative venue schedules (Binance, Coinbase, Kraken, OKX, Bybit,
  Bitfinex). Rates and impact parameters are indicative — calibrate to live
  data before real routing.
- `MODEL.tex`/`.pdf` formal specification; 15 correctness tests.
