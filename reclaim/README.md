# Recovery Engine | Blockchain Value Intelligence

**Working local-first MVP:** discover public blockchain addresses from historical EVM blocks, scan native token and allowlisted USDC balances, maintain a SQLite watchlist, export observations, and model liquidation economics. No Lovable credits or external Python packages are required.

> **Security:** This is a read-only analysis tool. It does not generate or guess private keys, bypass account controls, sign transactions, transfer coins, connect customer wallets, or take custody. Inactivity is not evidence of abandonment or permission to spend. Aave liquidation opportunities are separate from wallet recovery.

## Start

Python 3.11 or newer:

```bash
python3 server.py
```

Open `http://127.0.0.1:8765` in a browser. SQLite DB is created automatically. Local loopback mode does not require an app token. Run tests:

```bash
python3 -m unittest discover -s tests -v
```

For another port, use `PORT=8899 python3 server.py`. For remote access, set `HOST=0.0.0.0 APP_TOKEN=<random-long-secret>` **behind HTTPS and strong authentication**; not recommended to put this prototype directly on the public internet. Set `RPC_URL_ETHEREUM`, `RPC_URL_BASE`, etc. to dedicated private RPC endpoints for scanning at scale. `APP_TOKEN` is never written into code or storage.

## Features built

- Import wallet addresses (up to 100 per batch), with regex validation and per-chain de-duplication.
- Sample public `from` and `to` addresses from historical EVM blocks by block number (up to 75 per request). No claims about those addresses' current ownership or inactivity.
- Live JSON-RPC reads using `eth_getBalance`, ERC-20 `balanceOf` for verified USDC contracts. Supports Ethereum, Base, Arbitrum, and Polygon.
- Indicative USD values only if both native token and USDC spot quotes are available from CoinGecko. If unavailable, show unavailable, never an invented number.
- Read-only dashboard, data export and audit timestamp. Historical activity indexer intentionally not implemented; last activity and dormancy remain **unknown**.
- Educational Aave-style liquidation economics and health-factor estimation. **Not** a live quote, position monitor, eligibility verification, or order execution.
- Local SQLite persistence; a separate optional Supabase schema is provided for a dedicated future deployment.
- Localhost-only default, bearer token option, bounded input lengths and batch sizes, safe static asset serving, CSP, and no secrets checked into source.

## HTTP API

`GET /api/health`, `GET /api/chains`, `GET /api/wallets`, `GET /api/export.csv`.

`POST /api/wallets`:

```json
{"chain":"base", "addresses":["0x0000000000000000000000000000000000000001"]}
```

`POST /api/scan`: `{"ids":[1,2]}`. Public RPC responses may fail or rate-limit; errors are reported per address. `POST /api/discover`: `{"chain":"ethereum","block_number":16000000}`. `POST /api/simulate` accepts scenario amounts: `collateral_usd`, `debt_usd`, `liquidation_threshold_pct`, `repay_usd`, `bonus_pct`, `gas_usd`, `swap_fee_usd`, `slippage_pct`, `capital_cost_usd`.

When APP_TOKEN is configured, pass `Authorization: Bearer <token>` on `/api/*` calls. No paid API keys are necessary for basic operation, but public RPC capacity is limited. CoinGecko is an unauthenticated price source and can also rate-limit.

## Roadmap

1. **Historical activity indexer:** Alchemy/Bitquery or chain ETL with proper transaction indexing, dates and confidence levels. Real dormancy cannot be inferred from a static balance alone.
2. **Permissionless opportunity adapters:** protocol-supported liquidation / public bounty adapters with validated deployment addresses, ABI versions, position snapshots, and profitability checks.
3. **Dry-run executor:** `eth_call` simulations, liquidity / close factor checks, gas estimates and MEV risk analysis. Human approval before any execution.
4. **Owner-authorized recovery:** external wallet signatures / secure vault integrations. Never collect seed phrases or unprotected keys.
5. **Dedicated Supabase project:** apply `supabase/schema.sql` in a new project after reviewing RLS. Existing Aetheris / Ask Intros databases are not touched.
6. **Off-ramp:** approved swap integrations and fiat payout provider with required identity/compliance checks. No fake wallet cash-out claims.

## Scope limits

This MVP scans **addresses supplied by the user or sampled from specific blocks**, not every wallet on every chain. Sampling a block does not prove the address is dormant. No price history, no exact liquidation live state, no signing, and no guaranteed income. All displayed balances are public on-chain information, not money this application controls.
