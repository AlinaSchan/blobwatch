"""command line entry point: blobwatch [--blocks 50 | --since 1h] [--receipts] [--json] [--csv FILE]"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
import urllib.request
from datetime import datetime, timezone

from . import __version__
from .blobs import KNOWN, from_eth_config, merge
from .posters import Namer, load_labels
from .rpc import Rpc, RpcError, RpcUnavailable
from .scan import first_block_since, group, scan

USER_AGENT = "blobwatch/0.1 (+https://github.com/alinaschanz/blobwatch)"
CSV_FIELDS = ("block", "time_utc", "tx", "from", "to", "poster", "blobs", "blob_base_fee_wei", "paid_wei", "exec_paid_wei")
ORIGINS = (("table", "from the table"), ("chain", "read from the chain"), ("labels", "from your file"), ("unlabeled", "unlabeled"))


def parse_since(text: str) -> int:
    """'90m', '2h', '1d', '600s' -> seconds."""
    m = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", text.lower())
    if not m or int(m.group(1)) == 0:
        raise ValueError(f"not a duration: {text!r} (try 30m, 2h, 1d)")
    return int(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def _get_json(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def eth_usd(timeout: float = 15.0) -> float | None:
    """coingecko, and coinbase when coingecko says no (it rate-limits shared addresses)."""
    try:
        return float(_get_json("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd", timeout)["ethereum"]["usd"])
    except Exception:
        pass
    try:
        return float(_get_json("https://api.coinbase.com/v2/prices/ETH-USD/spot", timeout)["data"]["amount"])
    except Exception:
        return None


def fee_text(wei: float) -> str:
    return f"{wei:,.0f} wei" if wei < 1_000_000 else f"{wei / 1e9:.4g} gwei"


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def schedules_from(rpc) -> tuple[list, str]:
    try:
        live = from_eth_config(rpc.call("eth_config", []))
    except (RpcError, RpcUnavailable):
        live = []
    return (merge(KNOWN, live), "from eth_config") if live else (list(KNOWN), "built-in table, no eth_config on the node")


def summary(blocks, txs, posters, schedule_source: str, usd: float | None, receipts: bool = False) -> dict:
    fees = [b.fee for b in blocks]
    s = blocks[-1].schedule
    total = sum(b.blobs for b in blocks)
    return {
        "from_block": blocks[0].number, "to_block": blocks[-1].number, "blocks": len(blocks),
        "from_time_utc": iso(blocks[0].time), "to_time_utc": iso(blocks[-1].time),
        "schedule": {"fork": s.name, "target": s.target, "max": s.max, "update_fraction": s.fraction, "source": schedule_source},
        "blobs": total, "blobs_per_block": total / len(blocks),
        "blocks_full": sum(1 for b in blocks if b.blobs >= b.schedule.max), "blocks_empty": sum(1 for b in blocks if b.blobs == 0),
        "blob_base_fee_wei": {"last": fees[-1], "min": min(fees), "max": max(fees), "median": statistics.median(fees)},
        "paid_wei": sum(t.paid for t in txs), "exec_paid_wei": sum(t.exec_paid or 0 for t in txs) if receipts else None, "eth_usd": usd,
        "posters": [{"name": p.name, "source": p.source, "origin": p.origin, "blobs": p.blobs, "txs": p.txs, "paid_wei": p.paid,
                     "exec_paid_wei": p.exec_paid if receipts else None, "inboxes": sorted(p.inboxes), "senders": sorted(p.senders)}
                    for p in posters],
    }


def table(doc: dict, top: int) -> str:
    s, usd, fee, n = doc["schedule"], doc["eth_usd"], doc["blob_base_fee_wei"], doc["blocks"]
    total = doc["blobs"] or 1
    exec_on = doc["exec_paid_wei"] is not None
    spent = doc["paid_wei"] + (doc["exec_paid_wei"] or 0)
    t0, t1 = datetime.fromisoformat(doc["from_time_utc"]), datetime.fromisoformat(doc["to_time_utc"])
    minutes = max(1, round(((t1 - t0).total_seconds() + 12) / 60))  # n blocks cover n slots
    paid = f"paid for blob space: {doc['paid_wei'] / 1e18:.6f} eth"
    if exec_on:
        paid += f"; for the execution gas of the same transactions: {doc['exec_paid_wei'] / 1e18:.6f} eth"
    if usd:
        paid += f" (${spent / 1e18 * usd:,.2f}{' together' if exec_on else ''})"
    lines = [
        f"blob space on ethereum mainnet, blocks {doc['from_block']:,} to {doc['to_block']:,} "
        f"({n} blocks, about {minutes} min, {t0:%Y-%m-%d %H:%M} to {t1:%H:%M} utc)",
        f"schedule: target {s['target']}, max {s['max']} blobs a block ({s['fork']}, {s['source']})",
        f"blobs: {doc['blobs']:,}, {doc['blobs_per_block']:.1f} a block = {doc['blobs_per_block'] / s['target']:.0%} of the target, "
        f"{doc['blobs_per_block'] / s['max']:.0%} of the max; {doc['blocks_full']} blocks full, {doc['blocks_empty']} empty",
        f"blob base fee: {fee_text(fee['last'])} in the last block, {fee_text(fee['min'])} to {fee_text(fee['max'])} over the window",
        paid,
        "",
        f"{'poster':<26} {'blobs':>6} {'share':>6} {'txs':>5} {'blobs/tx':>8} "
        + (f"{'blob eth':>10} {'exec eth':>10}" if exec_on else f"{'paid eth':>10}") + (f" {'paid $':>8}" if usd else ""),
    ]
    for p in doc["posters"][:top]:
        line = (f"{p['name'][:26]:<26} {p['blobs']:>6,} {p['blobs'] / total:>6.1%} {p['txs']:>5,} {p['blobs'] / p['txs']:>8.1f} "
                f"{p['paid_wei'] / 1e18:>10.6f}") + (f" {p['exec_paid_wei'] / 1e18:>10.6f}" if exec_on else "")
        both = p["paid_wei"] + (p["exec_paid_wei"] or 0)
        lines.append(line + (f" {both / 1e18 * usd:>8.2f}" if usd else ""))
    rest = doc["posters"][top:]
    if rest:
        lines.append(f"({len(rest)} more, {sum(p['blobs'] for p in rest):,} blobs: --top {top + len(rest)} or --json)")
    counts = {origin: sum(1 for p in doc["posters"] if p["origin"] == origin) for origin, _ in ORIGINS}
    lines += ["", "names: " + ", ".join(f"{counts[o]} {words}" for o, words in ORIGINS if counts[o])
              + ". --json has the inbox and sender addresses and the source of every name."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="blobwatch", description="who bought ethereum's blob space, and what they paid. public rpc, no keys.")
    ap.add_argument("--blocks", type=int, default=50, help="how many of the latest blocks (default 50, about ten minutes)")
    ap.add_argument("--since", metavar="DURATION", help="a time window instead, e.g. 30m or 1h (a full block is about half a megabyte)")
    ap.add_argument("--to-block", type=int, metavar="N", help="end the window at this block instead of the head")
    ap.add_argument("--receipts", action="store_true",
                    help="add the execution gas of the same transactions (eth_getBlockReceipts, about as much data again)")
    ap.add_argument("--top", type=int, default=15, help="posters in the table (default 15)")
    ap.add_argument("--labels", metavar="FILE", help="json {address: name} on top of the built-in names")
    ap.add_argument("--no-resolve", action="store_true", help="no extra eth_call to name inboxes nobody wrote down")
    ap.add_argument("--no-usd", action="store_true", help="no eth price (coingecko, coinbase)")
    ap.add_argument("--json", action="store_true", help="json instead of the table")
    ap.add_argument("--csv", metavar="FILE", help="one row per blob transaction to this file")
    ap.add_argument("--rpc", action="append", metavar="URL", help="json-rpc endpoint (repeatable, tried in order)")
    ap.add_argument("--version", action="version", version=f"blobwatch {__version__}")
    args = ap.parse_args(argv)

    try:
        seconds = parse_since(args.since) if args.since else None
        labels = load_labels(args.labels) if args.labels else {}
    except (ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.blocks < 1 or args.top < 1:
        print("error: --blocks and --top want a positive number", file=sys.stderr)
        return 2
    rpc = Rpc(args.rpc) if args.rpc else Rpc()
    try:
        schedules, schedule_source = schedules_from(rpc)
        last = args.to_block if args.to_block is not None else rpc.block_number() - 1
        head_time = int(rpc.header(last)["timestamp"], 16) if seconds else 0
        first = first_block_since(rpc, last, head_time, seconds) if seconds else max(0, last - args.blocks + 1)
        blocks, txs = scan(rpc, list(range(first, last + 1)), schedules, receipts=args.receipts)
        posters, names = group(txs, Namer(rpc, labels, resolve=not args.no_resolve))
    except (RpcError, RpcUnavailable, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    doc = summary(blocks, txs, posters, schedule_source, None if args.no_usd else eth_usd(), receipts=args.receipts)
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            w.writeheader()
            for t in txs:
                w.writerow({"block": t.block, "time_utc": iso(t.time), "tx": t.hash, "from": t.sender, "to": t.to, "poster": names[t.hash],
                            "blobs": t.blobs, "blob_base_fee_wei": t.fee, "paid_wei": t.paid,
                            "exec_paid_wei": "" if t.exec_paid is None else t.exec_paid})
    print(json.dumps(doc, indent=2) if args.json else table(doc, args.top))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
