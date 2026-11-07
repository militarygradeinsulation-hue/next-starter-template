"""Read-only EVM wallet discovery and conservative liquidation economics.

No signing, transfer, withdrawal, transaction broadcast, or private key handling.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")

# Official native USDC contract addresses on supported networks.
CHAINS = {
    "ethereum": {
        "label": "Ethereum", "symbol": "ETH", "price_id": "ethereum",
        "rpc_env": "RPC_URL_ETHEREUM", "rpc_default": "https://ethereum-rpc.publicnode.com",
        "usdc": "0xA0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        "explorer": "https://etherscan.io/address/",
    },
    "base": {
        "label": "Base", "symbol": "ETH", "price_id": "ethereum",
        "rpc_env": "RPC_URL_BASE", "rpc_default": "https://mainnet.base.org",
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "explorer": "https://basescan.org/address/",
    },
    "arbitrum": {
        "label": "Arbitrum", "symbol": "ETH", "price_id": "ethereum",
        "rpc_env": "RPC_URL_ARBITRUM", "rpc_default": "https://arb1.arbitrum.io/rpc",
        "usdc": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        "explorer": "https://arbiscan.io/address/",
    },
    "polygon": {
        "label": "Polygon", "symbol": "POL", "price_id": "polygon-ecosystem-token",
        "rpc_env": "RPC_URL_POLYGON", "rpc_default": "https://polygon-bor-rpc.publicnode.com",
        "usdc": "0x3c499c542cef5E3811e1192ce70d8cc03d5c3359",
        "explorer": "https://polygonscan.com/address/",
    },
}


def validate_address(address: str) -> str:
    if not isinstance(address, str) or not ADDRESS_RE.fullmatch(address.strip()):
        raise ValueError("Enter a valid 0x-prefixed 20-byte EVM address.")
    return address.strip().lower()


def validate_chain(chain: str) -> str:
    if chain not in CHAINS:
        raise ValueError("Unsupported chain. Choose ethereum, base, arbitrum, or polygon.")
    return chain


def rpc_url(chain: str) -> str:
    entry = CHAINS[validate_chain(chain)]
    return os.getenv(entry["rpc_env"], entry["rpc_default"])


def json_request(url: str, payload: dict | None = None, *, timeout: int = 12) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"User-Agent": "RecoveryEngine-MVP/0.1", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read(2_000_000).decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise RuntimeError("Provider request failed; check RPC configuration or rate limits.") from exc


def rpc_call(chain: str, method: str, params: list) -> Any:
    response = json_request(rpc_url(chain), {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if not isinstance(response, dict):
        raise RuntimeError("Unexpected RPC response")
    if "error" in response:
        error = response["error"]
        raise RuntimeError(f"RPC error: {str(error.get('message','unknown'))[:160]}")
    if "result" not in response:
        raise RuntimeError("RPC response missing result")
    return response["result"]


def fetch_prices() -> dict[str, Decimal]:
    """Indicative spot prices. No fabricated prices if the API is unavailable."""
    ids = "ethereum,polygon-ecosystem-token,usd-coin"
    data = json_request("https://api.coingecko.com/api/v3/simple/price?ids=" + ids + "&vs_currencies=usd")
    result = {}
    for price_id in ids.split(","):
        value = data.get(price_id, {}).get("usd") if isinstance(data, dict) else None
        if value is not None:
            result[price_id] = Decimal(str(value))
    return result


def scan_wallet(chain: str, address: str, prices: dict[str, Decimal] | None = None) -> dict:
    """Get public native + allowlisted USDC balance; does NOT establish wallet inactivity."""
    chain = validate_chain(chain)
    address = validate_address(address)
    cfg = CHAINS[chain]
    native_hex = rpc_call(chain, "eth_getBalance", [address, "latest"])
    usdc_call = "0x70a08231" + address[2:].rjust(64, "0")
    usdc_hex = rpc_call(chain, "eth_call", [{"to": cfg["usdc"], "data": usdc_call}, "latest"])
    wei = int(native_hex, 16)
    units = int(usdc_hex, 16)
    if wei < 0 or units < 0:
        raise RuntimeError("Invalid negative balance returned by RPC")
    native = Decimal(wei) / Decimal(10**18)
    usdc = Decimal(units) / Decimal(10**6)
    native_price = (prices or {}).get(cfg["price_id"])
    usdc_price = (prices or {}).get("usd-coin")
    usd = native * native_price + usdc * usdc_price if native_price is not None and usdc_price is not None else None
    return {
        "chain": chain, "address": address, "native_symbol": cfg["symbol"],
        "native_balance": str(native), "usdc_balance": str(usdc),
        "estimated_usd": str(usd.quantize(Decimal("0.01"))) if usd is not None else None,
        "price_status": "spot_estimate" if usd is not None else "unavailable",
        "last_activity": None, "dormancy_verified": False,
        "recoverability": "ownership_authorization_required",
        "explorer_url": cfg["explorer"] + address,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


def discover_block(chain: str, block_number: int, maximum: int = 75) -> list[str]:
    """Sample PUBLIC addresses from one historical block, never assess ownership."""
    validate_chain(chain)
    if isinstance(block_number, bool) or not isinstance(block_number, int) or block_number < 0:
        raise ValueError("Block number must be a nonnegative integer")
    if maximum < 1 or maximum > 100:
        raise ValueError("maximum out of bounds")
    block = rpc_call(chain, "eth_getBlockByNumber", [hex(block_number), True])
    if not block:
        raise ValueError("Block not found on the selected chain")
    unique = set()
    result = []
    for tx in block.get("transactions", []):
        for field in ("from", "to"):
            value = tx.get(field)
            if isinstance(value, str) and ADDRESS_RE.fullmatch(value):
                address = value.lower()
                if address not in unique:
                    unique.add(address)
                    result.append(address)
                    if len(result) >= maximum:
                        return result
    return result


def number(value: Any, name: str, *, maximum: str = "1000000000000") -> Decimal:
    try:
        item = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name} must be a valid number")
    if not item.is_finite() or item < 0 or item > Decimal(maximum):
        raise ValueError(f"{name} must be nonnegative and within range")
    return item


def liquidation_simulator(params: dict) -> dict:
    """Simple scenario calculator, NOT an Aave liquidation eligibility/execution quote."""
    collateral = number(params.get("collateral_usd", 0), "collateral_usd")
    debt = number(params.get("debt_usd", 0), "debt_usd")
    threshold = number(params.get("liquidation_threshold_pct", 80), "liquidation_threshold_pct", maximum="100")
    repayment = number(params.get("repay_usd", 0), "repay_usd")
    bonus = number(params.get("bonus_pct", 5), "bonus_pct", maximum="100")
    gas = number(params.get("gas_usd", 0), "gas_usd")
    swap_fee = number(params.get("swap_fee_usd", 0), "swap_fee_usd")
    slippage = number(params.get("slippage_pct", 0), "slippage_pct", maximum="100")
    capital = number(params.get("capital_cost_usd", 0), "capital_cost_usd")
    flash_loan_pct = number(params.get("flash_loan_fee_pct", 0), "flash_loan_fee_pct", maximum="100")
    mev_risk = number(params.get("mev_risk_usd", 0), "mev_risk_usd")
    min_net_profit = number(params.get("minimum_net_profit_usd", 0), "minimum_net_profit_usd")
    hf = collateral * (threshold / 100) / debt if debt else None
    eligible_by_hf = hf is not None and hf < 1
    # Aave v3 example-only close-factor screen. Reserve-specific policy can differ.
    close_factor_pct = Decimal(100) if hf is not None and (
        hf <= Decimal('0.95') or collateral < 2000 or debt < 2000) else Decimal(50)
    close_cap = debt * close_factor_pct / 100
    insufficient = repayment <= 0 or repayment > debt
    within_close_factor = repayment <= close_cap
    seized = min(repayment * (1 + bonus / 100), collateral)
    remaining_debt = max(Decimal(0), debt - repayment)
    remaining_collateral = max(Decimal(0), collateral - seized)
    # Aave dust constraints: a partial liquidation must not leave sub-$1000 dust.
    dust_rule_met = bool(remaining_debt == 0 or (
        remaining_debt >= Decimal(1000) and remaining_collateral >= Decimal(1000)))
    collateral_sufficient = repayment * (1 + bonus / 100) <= collateral
    gross = seized - repayment
    costs = gas + swap_fee + capital + seized * slippage / 100 + repayment * flash_loan_pct / 100 + mev_risk
    net = gross - costs
    fmt = lambda x: str(x.quantize(Decimal("0.01")))
    return {
        "health_factor": str(hf.quantize(Decimal("0.0001"))) if hf is not None else None,
        "hf_below_one": eligible_by_hf,
        "repayment_within_debt": not insufficient,
        "close_factor_pct": fmt(close_factor_pct),
        "maximum_repay_by_close_factor_usd": fmt(close_cap),
        "repayment_within_close_factor": within_close_factor,
        "remaining_debt_usd": fmt(remaining_debt),
        "remaining_collateral_usd": fmt(remaining_collateral),
        "partial_dust_rule_met": dust_rule_met,
        "collateral_sufficient_for_bonus": collateral_sufficient,
        "minimum_net_profit_usd": fmt(min_net_profit),
        "gross_profit_usd": fmt(gross),
        "estimated_costs_usd": fmt(costs),
        "estimated_net_usd": fmt(net),
        "scenario_profitable": bool(eligible_by_hf and not insufficient and within_close_factor
                                      and dust_rule_met and collateral_sufficient and net > min_net_profit),
        "execution_ready": False,
        "warnings": [
            "Hypothetical estimate only. Close-factor and dust rules model Aave documentation but do not verify chain/reserve-specific rules, actual debt assets, collateral or oracle pricing.",
            "Competitive execution can fail and incur transaction fees. No signing or transaction broadcast is implemented.",
        ],
    }
