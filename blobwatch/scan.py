"""fetch a window of blocks, pick out the blob transactions, price them, group them by poster."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .blobs import GAS_PER_BLOB, Schedule, blob_base_fee, schedule_at


@dataclass(frozen=True)
class Block:
    number: int
    time: int
    blobs: int
    excess: int
    fee: int  # wei per blob gas
    schedule: Schedule


@dataclass(frozen=True)
class BlobTx:
    block: int
    time: int
    hash: str
    sender: str
    to: str
    blobs: int
    fee: int  # wei per blob gas, the block's blob base fee
    head: str  # the first 36 bytes of the calldata: a selector and one word

    @property
    def paid(self) -> int:
        """wei burned for the blob space. the execution gas of the same transaction is not in it."""
        return self.blobs * GAS_PER_BLOB * self.fee


def read_block(raw: dict, schedules) -> tuple[Block, list[BlobTx]]:
    """one full block -> its blob numbers and its blob transactions; everything else is dropped here."""
    number, ts = int(raw["number"], 16), int(raw["timestamp"], 16)
    schedule = schedule_at(ts, schedules)
    excess = int(raw.get("excessBlobGas") or "0x0", 16)
    fee = blob_base_fee(excess, schedule.fraction)
    used = int(raw.get("blobGasUsed") or "0x0", 16)
    txs = []
    for tx in raw.get("transactions") or []:
        if not isinstance(tx, dict) or tx.get("type") != "0x3":
            continue
        txs.append(BlobTx(number, ts, tx["hash"], tx["from"].lower(), (tx.get("to") or "").lower(),
                          len(tx.get("blobVersionedHashes") or []), fee, (tx.get("input") or "0x")[:74]))
    return Block(number, ts, used // GAS_PER_BLOB, excess, fee, schedule), txs


def scan(rpc, numbers: list[int], schedules, workers: int = 4, per_request: int = 5) -> tuple[list[Block], list[BlobTx]]:
    """a full block is about half a megabyte, so each worker reads its few blocks and keeps only the blob part."""
    chunks = [numbers[i:i + per_request] for i in range(0, len(numbers), per_request)]

    def work(chunk):
        return [read_block(raw, schedules) for raw in rpc.blocks(chunk, full=True, per_request=per_request)]

    blocks: list[Block] = []
    txs: list[BlobTx] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for part in pool.map(work, chunks):
            for block, found in part:
                blocks.append(block)
                txs.extend(found)
    return blocks, txs


@dataclass
class Poster:
    name: str
    source: str
    origin: str
    inboxes: set[str] = field(default_factory=set)
    senders: set[str] = field(default_factory=set)
    blobs: int = 0
    txs: int = 0
    paid: int = 0


def group(txs: list[BlobTx], namer) -> tuple[list[Poster], dict[str, str]]:
    """posters by blobs, most first, and the poster of every transaction (hash -> name)."""
    posters: dict[str, Poster] = {}
    names: dict[str, str] = {}
    for tx in txs:
        found = namer.name(tx.to, tx.head)
        names[tx.hash] = found.name
        p = posters.setdefault(found.name, Poster(*found))
        p.inboxes.add(tx.to)
        p.senders.add(tx.sender)
        p.blobs += tx.blobs
        p.txs += 1
        p.paid += tx.paid
    return sorted(posters.values(), key=lambda p: (-p.blobs, p.name)), names


def header_time(rpc, number: int) -> int:
    return int(rpc.header(number)["timestamp"], 16)


def first_block_since(rpc, head: int, head_time: int, seconds: int) -> int:
    """the first block inside the last `seconds`, by bisecting header timestamps: slots are 12 s,
    but missed slots make any block count an estimate."""
    target = head_time - seconds
    hi = head
    lo = max(0, head - 2 * (seconds // 12) - 10)
    while lo > 0 and header_time(rpc, lo) >= target:  # not old enough yet: step back further
        lo = max(0, lo - (hi - lo))
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if header_time(rpc, mid) >= target:
            hi = mid
        else:
            lo = mid
    return hi
