# blobwatch

[![ci](https://github.com/alinaschanz/blobwatch/actions/workflows/ci.yml/badge.svg)](https://github.com/alinaschanz/blobwatch/actions/workflows/ci.yml)
![python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776ab)
![license mit](https://img.shields.io/badge/license-MIT-2b7a74)
[![release](https://img.shields.io/github/v/release/alinaschanz/blobwatch?color=2b7a74)](https://github.com/alinaschanz/blobwatch/releases)
[![openssf scorecard](https://api.scorecard.dev/projects/github.com/alinaschanz/blobwatch/badge)](https://scorecard.dev/viewer/?uri=github.com/alinaschanz/blobwatch)

who bought ethereum's blob space in the last ten minutes, and what they paid for it. every blob
transaction of the last blocks, priced from the block header and grouped by the rollup that
posted it, read from a public json-rpc endpoint. no keys, no indexer, nothing to install but python.

```
$ blobwatch
blob space on ethereum mainnet, blocks 25,947,346 to 25,947,395 (50 blocks, about 10 min, 2026-09-10 13:40 to 13:49 utc)
schedule: target 14, max 21 blobs a block (bpo2, from eth_config)
blobs: 432, 8.6 a block = 62% of the target, 41% of the max; 0 blocks full, 1 empty
blob base fee: 0.0184 gwei in the last block, 0.01657 gwei to 0.024 gwei over the window
paid for blob space: 0.001150 eth ($2.79)

poster                      blobs  share   txs blobs/tx   paid eth   paid $
robinhood chain               138  31.9%    46      3.0   0.000367     0.89
base                          126  29.2%    21      6.0   0.000336     0.82
op mainnet                     40   9.3%     8      5.0   0.000104     0.25
unlabeled 0x002b..9449         32   7.4%     8      4.0   0.000086     0.21
arbitrum one                   21   4.9%     7      3.0   0.000057     0.14
world chain                    10   2.3%     2      5.0   0.000028     0.07
katana                          9   2.1%     2      4.5   0.000024     0.06
unichain                        9   2.1%     3      3.0   0.000025     0.06
sent to multicall3              8   1.9%     8      1.0   0.000021     0.05
lighter                         7   1.6%     7      1.0   0.000018     0.04
ink                             6   1.4%     1      6.0   0.000015     0.04
soneium                         5   1.2%     1      5.0   0.000013     0.03
arbitrum nova                   3   0.7%     3      1.0   0.000008     0.02
hemi                            2   0.5%     2      1.0   0.000005     0.01
mantle                          2   0.5%     2      1.0   0.000006     0.01
(11 more, 14 blobs: --top 26 or --json)

names: 18 from the table, 2 read from the chain, 6 unlabeled. --json has the inbox and sender addresses and the source of every name.
```

two things i did not expect when i first ran it: an arbitrum orbit chain, robinhood chain, posting
as many blobs as base, three at a time, and the fourth-biggest poster being an address nobody has
a name for. and the whole ten minutes of data availability for about twenty rollups cost less than
three dollars: blobs are 62% of the target, so the price sits near its floor.

## install

```
pipx install git+https://github.com/alinaschanz/blobwatch
```

or clone it and run `python -m blobwatch` from the folder. python 3.10 or newer, no dependencies.

## use

```
blobwatch                          # the last 50 blocks, about ten minutes
blobwatch --since 1h               # 300 blocks: about a minute and a half on a public node
blobwatch --to-block 25900000      # a window that ends somewhere in the past
blobwatch --receipts               # the execution gas of the same transactions too (twice the data)
blobwatch --json                   # every poster with its inboxes, senders and the source of its name
blobwatch --csv blobs.csv          # one row per blob transaction
blobwatch --labels mine.json       # {"0xinbox": "my rollup"} on top of the built-in names
blobwatch --no-resolve --no-usd    # no extra eth_call, no price lookup
```

## how it works

- **blocks.** `eth_getBlockByNumber` with full transactions, five blocks per batch request,
  four requests at a time, endpoints publicnode, mevblocker, drpc, tenderly, blastapi in that
  order (or `--rpc` yours). a full block is about half a megabyte, which is why the default is
  fifty; each block is reduced to its blob transactions as soon as it arrives.
- **blobs per block.** `blobGasUsed` in the header divided by 131,072 (one blob, 128 kib). the
  target and the max come from `eth_config` ([eip-7910](https://eips.ethereum.org/EIPS/eip-7910)),
  so the next blob parameter fork is picked up without a release; a node that does not answer
  it gets the built-in table (cancun 3/6, prague 6/9, bpo1 10/15, bpo2 14/21).
- **the price.** the blob base fee of a block is `fake_exponential(1, excessBlobGas, fraction)`
  from [eip-4844](https://eips.ethereum.org/EIPS/eip-4844), in integers, exactly as clients
  compute it; the live test checks it against `blobGasPrice` in a real receipt. a transaction
  pays blobs x 131,072 x that fee. there are no tips on blob gas, so this is what was burned for
  the space. the same transaction also pays ordinary gas for its calldata and the inbox's work;
  `--receipts` reads every receipt of the window (`eth_getBlockReceipts`) and adds gas used x
  effective gas price, base fee and tip, as a second column.
- **who posted it.** a blob transaction is sent to an inbox. in this order:
  1. your `--labels` file;
  2. a zk stack commit (`commitBatchesSharedBridge`) names the chain's diamond contract as its
     first argument, and the diamond answers `getChainId()`: the validator in front of those chains
     is shared, so the address alone would lump them together;
  3. [the table](blobwatch/posters.py), one source per line: the op
     [superchain registry](https://github.com/ethereum-optimism/superchain-registry), verified
     contracts on [blockscout](https://eth.blockscout.com), [blobscan](https://blobscan.com)'s attribution;
  4. the chain itself: an op stack batch inbox of the form `0xff00...8453` spells its chain id,
     and an arbitrum-style sequencer inbox answers `bridge()`, whose `rollup()` answers
     `chainId()`. that is how robinhood chain (4663) was named: nobody had written it down;
  5. everything else stays `unlabeled` with its address. a guess would be worse than a blank.
- chain ids become names through a short list from [ethereum-lists/chains](https://chainid.network).
- the dollar column is coingecko's eth price, coinbase's when coingecko says no. `--no-usd` skips it.

## reading the table

- `share` is of the blobs in the window, not of the gas. a rollup that posts six blobs per
  transaction and one that posts one are both in `blobs/tx`.
- 62% of the target means the blob base fee is falling block by block; above 100% it rises, by at
  most about 8% a block when a block is full. the fraction grows with the target since prague, so
  that step is the same at 6 blobs and at 14.
- `sent to multicall3` is a real contract with many unrelated senders, not a rollup.
- ten minutes are a small sample: base posts in bursts, robinhood chain every block or two. for
  anything you want to quote, `--since 1h` or longer.

## exit codes and scripting

`0` after a table, `2` when no rpc answered or a flag was wrong. `--json` carries every poster with
its inboxes, senders, blob count, transaction count and wei paid, plus the schedule and where it came
from, so `blobwatch --json | jq '.posters[] | select(.origin == "unlabeled") | .inboxes'` lists what
still needs a name.

## see also

- [gasweek](https://github.com/alinaschanz/gasweek): the execution side, base fee by hour of day
- [rpcprobe](https://github.com/alinaschanz/rpcprobe): which public endpoints answer, and what they let you do
- [onchain-notes](https://github.com/alinaschanz/onchain-notes): the blob fee on the daily card
- the notes: [alinaschanz.life](https://alinaschanz.life), the short version on [x](https://x.com/alinaschanz)

## verify a release

every release carries the sdist and the wheel, a `SHA256SUMS` file, an opentimestamps proof of that
file, and a build provenance attestation made in github's own signing flow. with the files downloaded
into one folder:

    sha256sum -c SHA256SUMS
    gh attestation verify ./*.whl --owner alinaschanz
    ots verify SHA256SUMS.ots

the commit itself is [signed](https://alinaschanz.life/verify/#commits).

## license

[mit](LICENSE). numbers, not calls. not financial advice.
