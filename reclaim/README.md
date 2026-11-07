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
