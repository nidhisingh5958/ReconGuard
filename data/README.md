# data/

Generated artefacts live here. Nothing in this directory is source of truth:
every dataset is reproducible from its seed.

    cd backend
    python -m scripts.generate_dataset --messy      # -> data/seed-500/

Each dataset directory contains `orders.json`, `settlements.json`,
`bank_statement.json`, `invoices.json`, `ground_truth.json` and `manifest.json`.
All monetary values are integer paise; the manifest states `"units": "paise"`.

`reconguard.db` is the SQLite database (runs, records, audit events, rules).
Delete it to start clean; it is recreated on API startup.
