# Recovery Engine | Blockchain Value Intelligence

**Working local-first Phase 2 MVP:** track and discover public EVM addresses, run bounded historical block discovery queues, scan native tokens and USDC, optionally index observed historical transfers with Etherscan V2, read live Aave V3 borrower health factors, maintain a SQLite ledger, export observations, and model hypothetical liquidation economics. No Lovable credits or external Python packages are required.

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
- Persistent discovery queues with checkpoints, pause and bounded batch runs (1 to 5 blocks each). On rate-limit or RPC failure, completed blocks retain their checkpoint for later retry. A configured scheduler can advance jobs automatically while the server runs.
- **Optional Etherscan V2 activity indexing:** requests normal, internal, ERC-20, ERC-721, and ERC-1155 event categories (up to 5 addresses per explicit batch). Records the latest observed transaction, days since observation, indexer coverage and partial failures. Requires `ETHERSCAN_API_KEY` and compatible API permissions; negative or incomplete results are never proof of dormancy. Even complete category coverage is not universal blockchain activity proof.
- **Live Aave V3 Pool view reads** on Ethereum, Base, Arbitrum and Polygon using official address-book pool contracts. Reads `getUserAccountData(address)`, stores health factors and flags *preliminary* sub-1 positions only when collateral and debt are nonzero. Results older than two minutes are labeled stale and must be rechecked. A flag is NOT proof of profitability or liquidation eligibility.
- Educational liquidation economics simulator, separately labeled hypothetical assumptions. **Not** a market quote or trading signal.
- Observations, Aave signals and activity signals displayed on the dashboard; extended CSV export.
- Local SQLite persistence; a separate optional Supabase schema is provided for a dedicated future deployment.
- Localhost-only default, bearer token option, bounded input lengths and batch sizes, safe static asset serving, CSP, and no secrets checked into source.

## HTTP API

`GET /api/health`, `GET /api/chains`, `GET /api/wallets`, `GET /api/export.csv`, `GET /api/opportunities`, `GET /api/monitor`, `GET /api/discovery/jobs`.

`POST /api/wallets`:

```json
{"chain":"base", "addresses":["0x0000000000000000000000000000000000000001"]}
```

`POST /api/scan`: `{"ids":[1,2]}`. Public RPC responses may fail or rate-limit; errors are reported per address. `POST /api/discover`: `{"chain":"ethereum","block_number":16000000}`. `POST /api/simulate` accepts scenario amounts: `collateral_usd`, `debt_usd`, `liquidation_threshold_pct`, `repay_usd`, `bonus_pct`, `gas_usd`, `swap_fee_usd`, `slippage_pct`, `capital_cost_usd`.

Other Phase 2 endpoints:

- `POST /api/discovery/jobs` — `{"chain":"ethereum","start_block":16000000,"end_block":16000020,"blocks_per_run":3}`. `end_block - start_block <= 10000`.
- `POST /api/discovery/jobs/run` — `{"job_id":1}`. Bounded batch. `POST /api/discovery/jobs/pause` and `POST /api/discovery/jobs/resume` — same ID.
- `POST /api/activity/scan` — `{"ids":[1,2]}`. Requires `ETHERSCAN_API_KEY`, up to 5 wallet IDs, five category API calls per wallet, sequential throttling. Free/provider plans and limits may restrict some chains.
- `POST /api/aave/scan` — `{"ids":[1,2]}`. Up to 20 IDs, reads Aave V3 pool snapshots via RPC, stores signals. `GET /api/opportunities` returns only preliminary position candidates with `execution_ready=false` and no estimated profit.

**Periodic background mode:** `AUTO_SCAN_INTERVAL_MINUTES=30 AUTO_SCAN_BATCH_LIMIT=10 python3 server.py` scans the least recently checked *tracked wallets* every 30 minutes. Add `AUTO_DISCOVERY_ENABLED=1` to also advance the oldest active discovery queue by at most two blocks each tick. Defaults for both are OFF to conserve RPC usage. The process must remain online; this is not a separately hosted scheduler. No signing, swaps, asset transfers or cash withdrawals can occur.

When APP_TOKEN is configured, pass `Authorization: Bearer <token>` on `/api/*` calls. No paid API keys are necessary for basic operation, but public RPC capacity is limited. CoinGecko is an unauthenticated price source and can also rate-limit.

## Roadmap

1. **Protocol-specific discovery:** index Aave V3 borrower activity directly via verified pool events, rather than relying on arbitrary sampled address lists. Deduplicate borrowers and avoid cross-protocol assumptions.
2. **Validated opportunities:** per-market reserve data, oracle prices, close-factor rules, available collateral and gas/slippage estimates. Only classify as actionable after the full on-chain simulation succeeds.
3. **Optional read-only dry run:** simulate a complete strategy without broadcasting a transaction. Establish profit thresholds and execution/MEV risk. No execution enabled until separately reviewed and approved.
4. **Owner-authorized recovery:** external wallet signatures / secure vault integrations. Never collect seed phrases or unprotected keys.
5. **Dedicated Supabase project:** `supabase/schema.sql` is an optional **Phase 1 preliminary schema** only; it does NOT model all Phase 2 activity, Aave or discovery tables. Extend and review RLS before applying in a NEW project. No existing Aetheris / Ask Intros database was changed.
6. **Off-ramp:** approved swap integrations and fiat payout provider with any required identity/compliance checks. No fake wallet cash-out claims.

## Scope limits

This MVP scans **addresses supplied by the user or sampled from selected blocks / bounded discovery queues**, not every wallet on every chain. Sampling a block does not prove the address is dormant. No price history, no exact liquidation live state, no signing, and no guaranteed income. All displayed balances are public on-chain information, not money this application controls.

## Source validation and cost boundaries

- Aave Pool ABI: https://aave.com/docs/aave-v3/smart-contracts/pool
- Aave official address book: https://github.com/aave-dao/aave-address-book (Ethereum, Base, Arbitrum, Polygon Pool addresses checked on November 7, 2026)
- Etherscan V2: https://docs.etherscan.io/ (API key is not committed, provider quotas and paid features vary)
- RPC/price provider availability depends on network access. Unit tests mock external services and cost **zero** network calls. Live RPC/indexer calls have NOT been verified end to end in this environment.
- The application contains no transaction signing or withdrawal code. Indexed age and Aave risk signals are **not** funds the application can control.


## Phase 3: Borrower discovery from Aave V3 events

The **Opportunity lab** now has an Aave borrower discovery queue that indexes verified `Borrow` events emitted by the official Aave V3 Pool contracts on Ethereum, Base, Arbitrum, and Polygon. Instead of scanning random wallet addresses, the discovery worker retrieves accounts on whose behalf borrowing occurred. The borrower is decoded from indexed `topic2` (`onBehalfOf`), not guessed from transaction sender. Event signature: `Borrow(address,address,address,uint256,uint8,uint256,uint16)`.

1. Select a chain in the Opportunity lab and create a recent-block queue. Creation queries `eth_blockNumber` and reserves **20 blocks of confirmation distance** to reduce shallow reorg exposure. Default lookback is 5,000 blocks, and the batch size is 250 blocks (maximum 2,000).
2. Press **Index batch + check positions**. Event logs are validated for Pool origin, topic hash, ABI address padding, block range, transaction hash, and log index; event entries are unique by `(chain, tx_hash, log_index)`. The queue advances its checkpoint only after successful validation and a committed SQLite transaction.
3. New borrowers enter the existing watchlist with provenance `aave_borrow_event`. The dashboard then invokes `getUserAccountData` for up to 20 discovered borrowers in the batch. The live check is independent of event insertion; a failed position read does not erase already validated evidence.
4. Re-run until complete or pause/resume. `AUTO_AAVE_BORROWER_ENABLED=1` can advance the latest active queue on each scanner tick, provided `AUTO_SCAN_INTERVAL_MINUTES` is positive.

**Important:** Borrow event history does not establish an outstanding debt, current liquidation eligibility or profitability. Actual liquidation execution remains disabled. A position with a health factor below 1 is a *triage candidate only*. Trading still requires reserve-level debt/collateral data, close-factor confirmation, price-oracle normalization, available capital, live swap route, gas simulation, and competitive execution analysis.

### API

- `GET /api/aave/borrowers/jobs`: current Aave borrower indexing queues.
- `POST /api/aave/borrowers/jobs`: create a queue from `chain`, `lookback_blocks`, `blocks_per_run`, and `confirmations`.
- `POST /api/aave/borrowers/jobs/run`: index and checkpoint one batch using `job_id`.
- `POST /api/aave/borrowers/jobs/pause` and `/resume`: pause/resume queue by `job_id`.
- `GET /api/aave/borrowers/events`: inspect the latest on-chain event evidence, including raw block numbers and transaction hashes.

### Additional scenario checks

The hypothetical liquidation calculator now models Aave's documented V3 50%/100% close-factor split and minimum remaining balance constraints. It rejects a profitable flag when the modeled repayment exceeds the close factor, leaves prohibited dust, lacks collateral for the modeled bonus, or falls below `minimum_net_profit_usd`. It supports optional `flash_loan_fee_pct` and `mev_risk_usd`. **These rules are a preliminary gate, not a reserve-specific on-chain execution quote.**

The first run requires a reliable EVM RPC endpoint with `eth_getLogs`. Public shared RPC endpoints frequently restrict log range, response size, or rate. Smaller batches and dedicated providers are recommended. An empty batch does not mean the full lookback has no borrowers.

Sources: https://github.com/aave-dao/aave-v3-origin/blob/main/src/contracts/interfaces/IPool.sol and https://aave.com/help/borrowing/liquidations
