"""talks to a public rpc. skipped unless BLOBWATCH_LIVE=1."""
import os

import pytest

from blobwatch import posters
from blobwatch.blobs import KNOWN, blob_base_fee, from_eth_config, merge, schedule_at
from blobwatch.posters import Namer
from blobwatch.rpc import Rpc, RpcUnavailable

pytestmark = pytest.mark.skipif(os.environ.get("BLOBWATCH_LIVE") != "1", reason="set BLOBWATCH_LIVE=1")


def test_the_fee_formula_matches_what_receipts_say():
    rpc = Rpc()
    head = rpc.block_number() - 2
    for number in range(head, head - 20, -1):
        block = rpc.blocks([number])[0]
        blob_txs = [t for t in block["transactions"] if t.get("type") == "0x3"]
        if not blob_txs:
            continue
        receipt = rpc.call("eth_getTransactionReceipt", [blob_txs[0]["hash"]])
        fraction = schedule_at(int(block["timestamp"], 16)).fraction
        assert blob_base_fee(int(block["excessBlobGas"], 16), fraction) == int(receipt["blobGasPrice"], 16)
        return
    pytest.skip("no blob transaction in the last 20 blocks")


def test_the_table_is_not_behind_eth_config():
    try:
        live = from_eth_config(Rpc().call("eth_config", []))
    except RpcUnavailable:
        pytest.skip("no endpoint answers eth_config")
    current = live[0]
    assert merge(KNOWN, live)[-1].activation >= KNOWN[-1].activation
    if current.activation == KNOWN[-1].activation:
        assert (current.target, current.max, current.fraction) == (KNOWN[-1].target, KNOWN[-1].max, KNOWN[-1].fraction)


@pytest.mark.parametrize("inbox", [a for a, (_, source) in posters.KNOWN.items() if source.startswith("chainId()")])
def test_arbitrum_inboxes_in_the_table_say_the_same_on_chain(inbox):
    name, source = posters.KNOWN[inbox]
    chain = Namer(Rpc()).arbitrum_chain(inbox)
    assert f"chainId() {chain} " in source and posters.CHAINS[chain] == name


def test_the_zksync_era_diamond_says_324():
    diamond = "0x32400084c286cf3e17e7b677ea9583e60a000324"
    commit = "0x" + posters.ZK_COMMIT_BY_ADDRESS + diamond[2:].rjust(64, "0")
    assert Namer(Rpc()).zk_chain(commit) == 324
