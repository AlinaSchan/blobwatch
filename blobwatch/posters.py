"""who posted a blob: the inbox a blob transaction went to, named the long way round where the chain can say it.

in this order:
1. your own file (`--labels`);
2. a zk stack commit carries its chain: the validator timelock in front of those chains is
   shared, so the address alone would lump them together. the first argument of the commit is
   the chain's diamond contract, which answers getChainId();
3. the table below, one source per line;
4. what the chain says about an address nobody wrote down: an op stack batch inbox of the form
   0xff00...<chain id> spells its chain id, an arbitrum-style sequencer inbox answers
   bridge() -> rollup() -> chainId();
5. everything else is "unlabeled", with its address. a guess would be worse than a blank.
"""
from __future__ import annotations

import json
import re
from typing import NamedTuple

from .rpc import RpcError, RpcUnavailable

# chain ids that post to mainnet, named after ethereum-lists/chains (chainid.network), shortened
CHAINS = {
    10: "op mainnet", 130: "unichain", 169: "manta pacific", 177: "hashkey chain", 232: "lens", 252: "fraxtal", 288: "boba",
    324: "zksync era", 360: "shape", 388: "cronos zkevm", 480: "world chain", 690: "redstone", 1088: "metis", 1101: "polygon zkevm",
    1135: "lisk", 1750: "metal l2", 1868: "soneium", 1923: "swellchain", 2741: "abstract", 2818: "morph", 4663: "robinhood chain",
    5000: "mantle", 5330: "superseed", 5371: "settlus", 7560: "cyber", 8008: "polynomial", 8453: "base", 33139: "apechain",
    34443: "mode", 42069: "pegglecoin", 42161: "arbitrum one", 42170: "arbitrum nova", 42220: "celo", 43111: "hemi",
    48900: "zircuit", 50104: "sophon", 57073: "ink", 59144: "linea", 60808: "bob", 61166: "treasure", 81457: "blast",
    98866: "plume", 167000: "taiko", 193939: "r0ar chain", 534352: "scroll", 543210: "zero network", 660279: "xai",
    747474: "katana", 2702128: "xterio", 7777777: "zora", 20240603: "dbk chain",
}

REGISTRY = "superchain registry (batch_inbox_addr)"
BLOBSCAN = "blobscan's attribution"

# inbox address -> (name, where the name comes from)
KNOWN: dict[str, tuple[str, str]] = {
    "0xff00000000000000000000000000000000000010": ("op mainnet", REGISTRY),
    "0x005969bf0ecbf6edb6c47e5e94693b1c3651be97": ("ink", REGISTRY),
    "0xff00000000000000000000000000000000000480": ("world chain", REGISTRY),
    "0xff00000000000000000000000000000000000130": ("unichain", REGISTRY),
    "0x008dc74cecc9deda8595b2fe210ce5979f0bfa8e": ("soneium", REGISTRY),
    "0xc83f7d9f2d4a76e81145849381aba02602373723": ("metal l2", REGISTRY),
    "0xff00000000000000000000000000000000000360": ("shape", REGISTRY),
    "0x24e59d9d3bd73ccc28dc54062af7ef7bff58bd67": ("mode", REGISTRY),
    "0xfff0000000000000000000000000000000000288": ("boba", REGISTRY),
    "0x6f54ca6f6ede96662024ffd61bfd18f3f4e34dff": ("zora", REGISTRY),
    "0x8612014a343089f1ddbacfd42baf4afbf9133593": ("superseed", REGISTRY),
    "0x003e40d3125591bd722ab1bb880c78e4d74d0977": ("settlus", REGISTRY),
    "0x0004cb44c80b6fbf8ceb1d80af688c9f7c0b2ab5": ("hashkey chain", REGISTRY),
    "0xff00000000000000000000000000000000001135": ("lisk", REGISTRY),
    "0x3a75346f81302aac0333fb5dcdd407e12a6cfa83": ("bob", REGISTRY),
    # base is not in the registry's mainnet folder; its inbox spells 8453 and blobscan agrees
    "0xff00000000000000000000000000000000008453": ("base", "inbox spells chain id 8453; " + BLOBSCAN),
    "0x1c479675ad559dc151f6ec7ed3fbf8cee79582b6": ("arbitrum one", "chainId() 42161 via bridge() and rollup()"),
    "0x211e1c4c7f1bf5351ac850ed10fd68cffcf6c21b": ("arbitrum nova", "chainId() 42170 via bridge() and rollup()"),
    "0xbd0d173eeb87d57a09521c24388a12789f33ba96": ("robinhood chain", "chainId() 4663 via bridge() and rollup()"),
    "0x3b4d794a66304f130a4db8f2551b0070dfcf5ca7": ("lighter", "verified contract ZkLighter (blockscout)"),
    "0xa13baf47339d63b743e7da8741db5456dac1e556": ("scroll", "verified contract ScrollChain (blockscout); " + BLOBSCAN),
    "0xd19d4b5d358258f05d7b411e21a1460d11b0876f": ("linea", "verified contract LineaRollup (blockscout); " + BLOBSCAN),
    "0xc662c410c0ecf747543f5ba90660f6abebd9c8c4": ("starknet", "verified contract Starknet (blockscout); " + BLOBSCAN),
    "0x6f21c543a4af5189ebdb0723827577e1ef57ef1f": ("taiko", "verified contract MainnetInbox (blockscout); " + BLOBSCAN),
    "0x759894ced0e6af42c26668076ffa84d02e3cef60": ("morph", "verified contract Rollup (blockscout); " + BLOBSCAN),
    "0xffeeddccbbaa0000000000000000000000000000": ("mantle", BLOBSCAN),
    "0x000d4411cdeb152378626b5c5e33fd5d6808939a": ("katana", BLOBSCAN),
    "0xf338cad020d506e8e3d9b4854986e0ece6c23640": ("paradex", BLOBSCAN),
    "0x8c12f051c161c2cda736f3b3fa1c4bdd35b7922c": ("codex", BLOBSCAN),
    "0xa150ff19a31e1054f950098869834affe9bc6fdc": ("symbiosis", BLOBSCAN),
    "0x5a2a0698355d06cd5c4e3872d2bc6b9f6a89d39b": ("phala", BLOBSCAN),
    "0x9937033cc967eed9d753e31c77d2f146d002ae53": ("bob", BLOBSCAN),
    "0xca11bde05977b3631167028862be2a173976ca11": ("sent to multicall3", "the multicall3 contract; many unrelated senders"),
}

# selectors, written out so nothing has to be hashed at runtime
SEL_BRIDGE = "e78cea92"  # bridge()
SEL_ROLLUP = "cb23bcb5"  # rollup()
SEL_CHAIN_ID = "9a8a0592"  # chainId()
SEL_GET_CHAIN_ID = "3408e470"  # getChainId(), on a zk stack diamond
ZK_COMMIT_BY_ADDRESS = "0db9eb87"  # commitBatchesSharedBridge(address,uint256,uint256,bytes)
ZK_COMMIT_BY_ID = "98f81962"  # commitBatchesSharedBridge(uint256,uint256,uint256,bytes)

_OP_INBOX = re.compile(r"0xf{2,}0+([0-9a-f]{1,10})")


class Name(NamedTuple):
    name: str
    source: str  # where the name comes from, in words
    origin: str  # "labels", "table", "chain" or "unlabeled"


def short(address: str) -> str:
    return address[:6] + ".." + address[-4:] if len(address) == 42 else address


def op_inbox_chain(address: str) -> int | None:
    """0xff00000000000000000000000000000000008453 -> 8453. the digits are usually the chain id in
    decimal, sometimes in hex (0xff...1d88 is 7560); the reading that is a known chain wins."""
    m = _OP_INBOX.fullmatch(address.lower())
    if not m:
        return None
    tail = m.group(1)
    readings = ([int(tail)] if tail.isdigit() else []) + [int(tail, 16)]
    return next((r for r in readings if r in CHAINS), readings[0])


def _word_address(data: bytes) -> str | None:
    if len(data) < 32 or any(data[:12]):
        return None
    address = "0x" + data[12:32].hex()
    return None if address == "0x" + "00" * 20 else address


def load_labels(path: str) -> dict[str, str]:
    """a json object {address: name}; addresses in any case."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {str(k).lower(): str(v) for k, v in raw.items()}


class Namer:
    def __init__(self, rpc, labels: dict[str, str] | None = None, resolve: bool = True):
        self.rpc = rpc
        self.labels = {k.lower(): v for k, v in (labels or {}).items()}
        self.resolve = resolve
        self._arbitrum: dict[str, int | None] = {}
        self._zk: dict[str, int | None] = {}

    def name(self, to: str, calldata: str = "0x") -> Name:
        """who sent a blob transaction to `to` with this calldata (the first 36 bytes are enough)."""
        to = (to or "").lower()
        if to in self.labels:
            return Name(self.labels[to], "your labels file", "labels")
        zk = self.zk_chain(calldata)
        if zk is not None:
            return Name(CHAINS.get(zk, f"zk stack chain {zk}"), f"the commit names chain id {zk}", "chain")
        if to in KNOWN:
            return Name(*KNOWN[to], "table")
        op = op_inbox_chain(to)
        if op is not None:
            return Name(CHAINS.get(op, f"op stack chain {op}"), f"inbox spells chain id {op}", "chain")
        if self.resolve:
            arb = self.arbitrum_chain(to)
            if arb is not None:
                return Name(CHAINS.get(arb, f"arbitrum chain {arb}"), f"chainId() {arb} via bridge() and rollup()", "chain")
        return Name("unlabeled " + short(to), "unlabeled", "unlabeled")

    def zk_chain(self, calldata: str) -> int | None:
        data = (calldata or "0x")[2:]
        if len(data) < 8 + 64:
            return None
        selector, first = data[:8], data[8:72]
        if selector == ZK_COMMIT_BY_ID:
            return int(first, 16)
        if selector != ZK_COMMIT_BY_ADDRESS or not self.resolve:
            return None
        diamond = "0x" + first[24:]
        if diamond not in self._zk:
            try:
                answer = self.rpc.eth_call(diamond, "0x" + SEL_GET_CHAIN_ID)
                self._zk[diamond] = int.from_bytes(answer[:32], "big") if len(answer) >= 32 else None
            except (RpcError, RpcUnavailable):
                self._zk[diamond] = None
        return self._zk[diamond]

    def arbitrum_chain(self, to: str) -> int | None:
        """sequencer inbox -> bridge -> rollup -> chainId. an eoa answers nothing, other contracts revert."""
        if to not in self._arbitrum:
            chain = None
            try:
                bridge = _word_address(self.rpc.eth_call(to, "0x" + SEL_BRIDGE))
                rollup = _word_address(self.rpc.eth_call(bridge, "0x" + SEL_ROLLUP)) if bridge else None
                if rollup:
                    answer = self.rpc.eth_call(rollup, "0x" + SEL_CHAIN_ID)
                    chain = int.from_bytes(answer[:32], "big") if len(answer) >= 32 else None
            except (RpcError, RpcUnavailable):
                chain = None
            self._arbitrum[to] = chain or None
        return self._arbitrum[to]
