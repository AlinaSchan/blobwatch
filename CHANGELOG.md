# changelog

all notable changes to blobwatch. the format follows [keep a changelog](https://keepachangelog.com/en/1.1.0/),
versions follow [semver](https://semver.org/) as far as a command line tool has an api.

## [0.1.0] - 2026-09-10

first cut: the blob transactions of the last blocks, priced and grouped by who posted them.

- the blob base fee of every block from its header (`fake_exponential`, checked against receipts by the live test);
  the schedule from `eth_config`, with a built-in table behind it for nodes that do not answer it
- posters named from a table with a source on every line (superchain registry, verified contracts, blobscan),
  from the chain itself (op stack inboxes that spell their chain id, arbitrum-style `bridge() -> rollup() -> chainId()`,
  the diamond a zk stack commit names), or left unlabeled
- the table, `--json`, `--csv` with one row per transaction, `--since 1h`, `--labels` for your own names
