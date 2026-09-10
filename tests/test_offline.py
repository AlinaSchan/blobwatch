"""offline: the blob fee maths, the schedule, naming posters, the scan and the table with a fake node."""
import csv
import json

import pytest

from blobwatch import cli, posters
from blobwatch.blobs import GAS_PER_BLOB, KNOWN, blob_base_fee, fake_exponential, from_eth_config, merge, schedule_at
from blobwatch.posters import Namer, op_inbox_chain
from blobwatch.rpc import RpcError, RpcUnavailable
from blobwatch.scan import first_block_since, group, scan

BASE_INBOX = "0xff00000000000000000000000000000000008453"
OP_INBOX = "0xff00000000000000000000000000000000000010"
ARB_INBOX = "0x" + "ab" * 20  # not in the table: named by asking the chain
BRIDGE, ROLLUP, DIAMOND = "0x" + "b1" * 20, "0x" + "c1" * 20, "0x" + "d1" * 20
EOA = "0x" + "12" * 20
CONFIG = {"current": {"activationTime": 1767747671, "blobSchedule": {"target": 14, "max": 21, "baseFeeUpdateFraction": 11684671}}}


def word(value: int) -> str:
    return value.to_bytes(32, "big").hex()


def addr_word(address: str) -> bytes:
    return bytes.fromhex(address[2:].rjust(64, "0"))


def test_fee_matches_a_mainnet_receipt():
    # block 25,947,178 (bpo2): excessBlobGas 208,481,365 in the header; its blob transactions paid 56,080,378 wei per blob gas
    assert blob_base_fee(208_481_365, 11_684_671) == 56_080_378


def test_fake_exponential_edges():
    assert fake_exponential(1, 0, 5_007_716) == 1
    assert blob_base_fee(0, 3_338_477) == 1
    assert abs(fake_exponential(1_000_000, 1_000_000, 1_000_000) - 2_718_281) <= 1  # e


def test_update_fraction_scales_with_the_target_since_prague():
    for s in KNOWN[1:]:
        assert abs(s.fraction / s.target - 834_619.3) < 0.2, s


def test_schedule_lookup_and_eth_config():
    assert schedule_at(1_767_747_671).name == "bpo2"
    assert schedule_at(1_767_747_670).name == "bpo1"
    with pytest.raises(ValueError):
        schedule_at(1_700_000_000)
    cfg = {**CONFIG, "next": {"activationTime": "0x6aafa600", "blobSchedule": {"target": 21, "max": 32, "baseFeeUpdateFraction": 17527006}}}
    live = from_eth_config(cfg)
    assert [s.name for s in live] == ["bpo2", "next"] and live[1].activation == 0x6AAFA600
    merged = merge(KNOWN, live)
    assert len(merged) == len(KNOWN) + 1 and merged[-1].max == 32
    assert schedule_at(0x6AAFA600 + 1, merged).target == 21
    assert from_eth_config(None) == [] and from_eth_config({"current": {"activationTime": 1}}) == []


def test_op_inbox_spells_its_chain_id():
    assert op_inbox_chain(BASE_INBOX) == 8453
    assert op_inbox_chain("0xFF00000000000000000000000000000000000010") == 10
    assert op_inbox_chain("0xfF00000000000000000000000000000000001d88") == 7560  # cyber writes it in hex
    assert op_inbox_chain("0xfff0000000000000000000000000000000000288") == 288
    assert op_inbox_chain("0xffeeddccbbaa0000000000000000000000000000") is None
    assert op_inbox_chain("0x5050f69a9786f081509234f1a7f4684b5e5b76c9") is None


class FakeRpc:
    """blocks by number, a few contracts that answer eth_call, eth_config."""

    def __init__(self, blocks=(), config=CONFIG):
        self.by_number = {int(b["number"], 16): b for b in blocks}
        self.config = config
        self.eth_calls = 0

    def eth_call(self, to, data, block="latest"):
        self.eth_calls += 1
        sel = data[2:10]
        if to == ARB_INBOX and sel == posters.SEL_BRIDGE:
            return addr_word(BRIDGE)
        if to == BRIDGE and sel == posters.SEL_ROLLUP:
            return addr_word(ROLLUP)
        if to == ROLLUP and sel == posters.SEL_CHAIN_ID:
            return bytes.fromhex(word(4663))
        if to == DIAMOND and sel == posters.SEL_GET_CHAIN_ID:
            return bytes.fromhex(word(324))
        if to == EOA:
            return b""  # an address without code answers nothing
        raise RpcError("execution reverted")

    def call(self, method, params):
        if method == "eth_config" and self.config:
            return self.config
        raise RpcUnavailable("method not found")

    def blocks(self, numbers, full=True, per_request=5):
        return [self.by_number[n] for n in numbers]

    def receipts(self, numbers, per_request=5):
        return [[{"transactionHash": t["hash"], "type": t["type"], "gasUsed": hex(50_000), "effectiveGasPrice": hex(2 * 10**9)}
                 for t in self.by_number[n]["transactions"]] for n in numbers]

    def block_number(self):
        return max(self.by_number) + 1

    def header(self, number):
        return self.by_number[number]


def zk_commit(diamond: str) -> str:
    return "0x" + posters.ZK_COMMIT_BY_ADDRESS + diamond[2:].rjust(64, "0") + word(7) + word(7)


def block(number, ts, excess, txs):
    body = []
    for i, (sender, to, n, data) in enumerate(txs):
        body.append({"type": "0x3", "hash": f"0x{number:04x}{i:060x}", "from": sender, "to": to, "input": data,
                     "blobVersionedHashes": ["0x01" + "00" * 31] * n})
    body.append({"type": "0x2", "hash": "0x" + "ee" * 32, "from": EOA, "to": EOA, "input": "0x"})
    return {"number": hex(number), "timestamp": hex(ts), "excessBlobGas": hex(excess),
            "blobGasUsed": hex(sum(t[2] for t in txs) * GAS_PER_BLOB), "transactions": body}


T0 = 1_789_000_000
BLOCKS = [
    block(100, T0, 208_481_365, [("0xba5e", BASE_INBOX, 6, "0x"), ("0xa7b", ARB_INBOX, 3, "0x"), ("0x0p", OP_INBOX, 2, "0x")]),
    block(101, T0 + 12, 0, [("0xba5e", BASE_INBOX, 6, "0x"), ("0x2c", "0x" + "de" * 20, 1, zk_commit(DIAMOND)), ("0x99", EOA, 1, "0x")]),
    block(102, T0 + 24, 0, []),
]


def test_namer_order_and_sources():
    namer = Namer(FakeRpc(), labels={EOA.upper().replace("0X", "0x"): "my test chain"})
    assert namer.name(BASE_INBOX) == ("base", posters.KNOWN[BASE_INBOX][1], "table")
    assert namer.name(EOA).name == "my test chain" and namer.name(EOA).origin == "labels"
    zk = namer.name("0x" + "de" * 20, zk_commit(DIAMOND))
    assert zk.name == "zksync era" and zk.origin == "chain" and "324" in zk.source
    assert namer.name("0x" + "de" * 20, "0x" + posters.ZK_COMMIT_BY_ID + word(2741) + word(1)).name == "abstract"
    arb = namer.name(ARB_INBOX)
    assert arb.name == "robinhood chain" and arb.origin == "chain" and "4663" in arb.source
    assert namer.name("0xff00000000000000000000000000000000048900").name == "zircuit"
    assert namer.name("0x" + "34" * 20).name == "unlabeled 0x3434..3434"


def test_namer_asks_the_chain_once_per_address_and_not_at_all_when_told():
    rpc = FakeRpc()
    namer = Namer(rpc)
    for _ in range(3):
        namer.name(ARB_INBOX)
        namer.name("0x" + "34" * 20)
    assert rpc.eth_calls == 3 + 1  # bridge, rollup, chainId once; one reverted bridge() for the unknown contract
    quiet = Namer(rpc, resolve=False)
    assert quiet.name(ARB_INBOX).origin == "unlabeled" and quiet.name("0x" + "de" * 20, zk_commit(DIAMOND)).origin == "unlabeled"


def test_scan_prices_and_groups():
    blocks, txs = scan(FakeRpc(BLOCKS), [100, 101, 102], list(KNOWN), workers=2, per_request=2)
    assert [b.number for b in blocks] == [100, 101, 102] and [b.blobs for b in blocks] == [11, 8, 0]
    assert blocks[0].fee == 56_080_378 and blocks[1].fee == 1
    assert len(txs) == 6 and all(t.head.startswith("0x") for t in txs)
    found, names = group(txs, Namer(FakeRpc()))
    assert [(p.name, p.blobs, p.txs) for p in found][:2] == [("base", 12, 2), ("robinhood chain", 3, 1)]
    base = found[0]
    assert base.paid == 6 * GAS_PER_BLOB * 56_080_378 + 6 * GAS_PER_BLOB * 1
    assert names[txs[0].hash] == "base" and len(names) == 6


def test_receipts_add_the_execution_side():
    _, txs = scan(FakeRpc(BLOCKS), [100, 101, 102], list(KNOWN), workers=2, per_request=2, receipts=True)
    assert len(txs) == 6 and all(t.exec_paid == 50_000 * 2 * 10**9 for t in txs)  # the type 2 transaction is not counted
    found, _ = group(txs, Namer(FakeRpc()))
    assert found[0].name == "base" and found[0].exec_paid == 2 * 50_000 * 2 * 10**9
    _, plain = scan(FakeRpc(BLOCKS), [100], list(KNOWN))
    assert all(t.exec_paid is None for t in plain)


def test_cli_with_receipts(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "Rpc", lambda urls=None: FakeRpc(BLOCKS))
    monkeypatch.setattr(cli, "eth_usd", lambda: 4000.0)
    path = tmp_path / "txs.csv"
    assert cli.main(["--blocks", "3", "--receipts", "--csv", str(path)]) == 0
    out = capsys.readouterr().out
    assert "blob eth   exec eth" in out and "for the execution gas of the same transactions: 0.000600 eth" in out and "together" in out
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["exec_paid_wei"] == str(50_000 * 2 * 10**9)
    assert cli.main(["--blocks", "3", "--receipts", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["exec_paid_wei"] == 6 * 50_000 * 2 * 10**9 and doc["posters"][0]["exec_paid_wei"] == 2 * 50_000 * 2 * 10**9
    assert cli.main(["--blocks", "3", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["exec_paid_wei"] is None


def test_first_block_since_bisects_timestamps():
    heads = {n: {"number": hex(n), "timestamp": hex(T0 + 12 * n + (12 if n > 500 else 0))} for n in range(0, 1001)}  # a missed slot at 501
    rpc = FakeRpc()
    rpc.by_number = heads
    assert first_block_since(rpc, 1000, T0 + 12 * 1000 + 12, 3600) == 700
    assert first_block_since(rpc, 1000, T0 + 12 * 1000 + 12, 12 * 600) == 401


def test_cli_table_json_and_csv(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "Rpc", lambda urls=None: FakeRpc(BLOCKS))
    monkeypatch.setattr(cli, "eth_usd", lambda: 4000.0)
    path = tmp_path / "txs.csv"
    assert cli.main(["--blocks", "3", "--csv", str(path)]) == 0
    out = capsys.readouterr().out
    assert "blocks 100 to 102 (3 blocks" in out and "target 14, max 21" in out and "from eth_config" in out
    assert "base" in out and "63.2%" in out and "robinhood chain" in out and "0 blocks full, 1 empty" in out
    assert "names: 2 from the table, 2 read from the chain, 1 unlabeled" in out
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 6 and rows[0]["poster"] == "base" and rows[0]["paid_wei"] == str(6 * GAS_PER_BLOB * 56_080_378)
    assert cli.main(["--blocks", "3", "--json", "--top", "1"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["blobs"] == 19 and doc["posters"][0]["inboxes"] == [BASE_INBOX] and doc["eth_usd"] == 4000.0
    assert doc["schedule"] == {"fork": "bpo2", "target": 14, "max": 21, "update_fraction": 11684671, "source": "from eth_config"}


def test_cli_without_eth_config_uses_the_table(monkeypatch, capsys):
    monkeypatch.setattr(cli, "Rpc", lambda urls=None: FakeRpc(BLOCKS, config=None))
    assert cli.main(["--blocks", "2", "--no-usd", "--top", "1"]) == 0
    out = capsys.readouterr().out
    assert "built-in table" in out and "paid $" not in out and "more," in out


def test_cli_rejects_bad_input(tmp_path):
    assert cli.main(["--since", "soon"]) == 2
    assert cli.main(["--blocks", "0"]) == 2
    assert cli.main(["--labels", str(tmp_path / "missing.json")]) == 2
    assert cli.parse_since("90m") == 5400 and cli.parse_since("1d") == 86400


def test_fee_text():
    assert cli.fee_text(1) == "1 wei" and cli.fee_text(56_080_378) == "0.05608 gwei"
