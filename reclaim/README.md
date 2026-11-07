# RECLAIM 0.5 — Real blockchain observations only

This project is a read-only blockchain intelligence service. **There are no demo balances, manual profit simulations, mock production data, fake transaction outcomes, trade execution, or wallet/private-key recovery claims.** Deterministic unit tests may patch provider replies to verify error handling; production never substitutes mock data.

## Start
```sh
cd reclaim
python3 server.py
```
Open http://127.0.0.1:8765. Python 3.11+ standard library and SQLite.

## Real data sources
- Live EVM JSON-RPC for balances and native USDC balance.
- Aave V3 Pool and ProtocolDataProvider contract reads at a **single pinned block** for reserve balances, on-chain liquidation bonus, current debt and collateral exposure, oracle unit/currency and health factor.
- Historical Aave V3 `Borrow` event indexing from JSON-RPC.
- Optional Etherscan V2 indexed activity with `ETHERSCAN_API_KEY`.
- CoinGecko spot prices for display, which may be unavailable due to rate limits.

Set `RPC_URL_ETHEREUM`, `RPC_URL_BASE`, `RPC_URL_ARBITRUM`, `RPC_URL_POLYGON` to reliable RPC URLs. Otherwise public best-effort endpoints are used. **Network Settings → Verify live networks** makes uncached requests for `eth_chainId` and `eth_blockNumber`, checks expected network IDs and displays unavailable networks explicitly. No fallback values are fabricated.

## Endpoints
- `GET /api/network/status`: actual RPC network identity and chain head.
- `POST /api/aave/reserves/analyze` with `{"ids":[1]}`: real pinned-block Aave reserve data.
- `GET /api/aave/reserves/analyses`: latest persisted, actual Aave snapshots.
- Other addresses, discovery jobs, Aave borrower events, monitoring, activity indexing and exports remain available.
- `POST /api/simulate` is removed. The scenario UI and all synthetic net-profit estimates are removed.

**No liquidation profit is claimed** until real swap routes, live transaction-level simulation, funding and full gas costs can be verified. An Aave risk signal is not an executable transaction. Dormant wallets do not become accessible merely because they are inactive.

```sh
python3 -m unittest discover -s tests -v
```

## 0x live market prices (Phase 6)
Configure `ZEROX_API_KEY` on the backend to enable live USDC route price requests for actual recorded Aave collateral reserves. The dashboard offers a **Live 0x price** action only for reserves with positive observed collateral quantities. Request `POST /api/market/price` with `{"wallet_id":1,"sell_asset":"0x..."}` after scanning the wallet in the past 120 seconds. This calls 0x API v2 `/swap/allowance-holder/price` with the actual equivalent underlying quantity read from Aave; it does **not** claim that collateral is owned by RECLAIM, available for transfer, liquidatable, or profitable. Provider key missing, unavailable liquidity, stale observation and malformed responses produce errors, never fabricated quotes. `GET /api/market/status` exposes configuration state without revealing the key. This is a price API only and neither requests an executable transaction nor signs one. Source: https://docs.0x.org/api-reference/evm-ap-is/swap/allowanceholder-getprice
