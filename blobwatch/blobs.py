"""eip-4844 blob gas: the price formula and the blob schedule (target, max, update fraction)."""
from __future__ import annotations

from dataclasses import dataclass

GAS_PER_BLOB = 2**17  # 131,072 blob gas per blob, 128 kib of data
MIN_BASE_FEE_PER_BLOB_GAS = 1  # wei


@dataclass(frozen=True)
class Schedule:
    name: str
    activation: int  # unix time of the fork
    target: int  # blobs per block
    max: int
    fraction: int  # BLOB_BASE_FEE_UPDATE_FRACTION


# mainnet, used when the node does not answer eth_config (eip-7910). since prague the update
# fraction scales with the target (about 834,619 per blob), so the price moves by the same
# percentage per block at every target: at most +/- about 8% when a block is full or empty.
KNOWN = (
    Schedule("cancun", 1710338135, 3, 6, 3338477),
    Schedule("prague", 1746612311, 6, 9, 5007716),
    Schedule("osaka", 1764798551, 6, 9, 5007716),
    Schedule("bpo1", 1765290071, 10, 15, 8346193),
    Schedule("bpo2", 1767747671, 14, 21, 11684671),
)


def fake_exponential(factor: int, numerator: int, denominator: int) -> int:
    """factor * e ** (numerator / denominator) in integers, term by term, as eip-4844 writes it
    and every client computes it. floats would be off by a few wei at high prices."""
    i = 1
    output = 0
    accum = factor * denominator
    while accum > 0:
        output += accum
        accum = (accum * numerator) // (denominator * i)
        i += 1
    return output // denominator


def blob_base_fee(excess_blob_gas: int, fraction: int) -> int:
    """wei per blob gas for a block with this excessBlobGas in its header."""
    return fake_exponential(MIN_BASE_FEE_PER_BLOB_GAS, excess_blob_gas, fraction)


def _num(value) -> int:
    if isinstance(value, str):
        return int(value, 16) if value.startswith("0x") else int(value)
    return int(value)


def from_eth_config(result: dict | None) -> list[Schedule]:
    """the blob schedules an eth_config answer carries (current, and next when a fork is scheduled)."""
    out = []
    for key in ("current", "next"):
        fork = (result or {}).get(key)
        if not fork or not fork.get("blobSchedule"):
            continue
        bs = fork["blobSchedule"]
        activation = _num(fork["activationTime"])
        name = next((k.name for k in KNOWN if k.activation == activation), key)
        out.append(Schedule(name, activation, _num(bs["target"]), _num(bs["max"]), _num(bs["baseFeeUpdateFraction"])))
    return out


def merge(known: tuple[Schedule, ...] | list[Schedule], extra: list[Schedule]) -> list[Schedule]:
    """the built-in table with whatever the node said on top: same activation time replaces, new ones are added."""
    by_time = {s.activation: s for s in known}
    for s in extra:
        by_time[s.activation] = s
    return [by_time[t] for t in sorted(by_time)]


def schedule_at(timestamp: int, schedules: list[Schedule] | tuple[Schedule, ...] = KNOWN) -> Schedule:
    current = None
    for s in sorted(schedules, key=lambda s: s.activation):
        if s.activation <= timestamp:
            current = s
    if current is None:
        raise ValueError("that block is older than cancun, there were no blobs yet")
    return current
