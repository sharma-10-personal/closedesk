# Run guide

Tested target: Apple Silicon Mac, 16 GB RAM, Exasol Personal local VM.

## 1. Exasol Personal

Needs about 8 GB RAM for the VM (this machine has 16 GB).

```bash
curl https://downloads.exasol.com/exasol-personal/installer.sh | sh
export PATH="$HOME/.local/bin:$PATH"
exasol install local --auto-approve --cpu-count 2 --memory-mb 8192 --data-size-gb 40
exasol status
# expect: database_ready
exasol connect -k -c "SELECT 1;"
```

Default SQL endpoint: `127.0.0.1:8563`, user `sys`. Password is in:

`~/.exasol/personal/deployments/default/secrets.json` (key `dbPassword`).

Do not commit that file. Copy it into `.env` as `EXA_PASSWORD`.

### AWS (optional)

```bash
exasol install aws
```

Requires your own AWS account. Not needed for judging if local works. Same SQL, same project commands after `EXA_DSN` points at the cloud endpoint.

## 2. This repository

Python 3.11+ (3.13 is fine).

```bash
git clone git@github.com-sharma-10:sharma-10-personal/closedesk.git
cd closedesk
cp .env.example .env
# set EXA_PASSWORD from secrets.json
make setup
make schema
make test
```

After the generator exists:

```bash
make data
make load
make run
make demo
```

`make reset` drops generated `data/` and reapplies `sql/00_schema.sql`.

## 3. What local Exasol cannot do (yet)

Python UDFs need `exasol slc install PYTHON3`. CloseDesk does not need that. Matching is SQL.

## 4. LLM

Leave `LLM_PROVIDER=none`. The UI must still explain a break from SQL labels.
