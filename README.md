# nsq2mariadb

Generic transporter for moving JSON messages from [NSQ](https://nsq.io/) topics into
[MariaDB](https://mariadb.org/) tables. You write one Python `Mapper` class per
topic; the framework handles the NSQ subscription, schema bootstrap, and
transactional inserts.

The shape mirrors [`nsq2arangodb`](https://github.com/larsborn/nsq2arangodb) —
but because MariaDB is schema-full, the per-topic schema and JSON-to-row
translation has to live in code rather than configuration.

## Installation

```bash
pip install git+https://github.com/larsborn/nsq2mariadb.git@v0.1.0
```

Or for local development:

```bash
git clone https://github.com/larsborn/nsq2mariadb.git
cd nsq2mariadb
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
```

Requires Python 3.9+. Dependencies: `pynsq`, `pymysql`.

## Usage

For each NSQ topic you want to consume, subclass `Mapper`:

```python
from nsq2mariadb import Mapper

class OrderMapper(Mapper):
    topic = "orders"
    schema_sql = """
        CREATE TABLE IF NOT EXISTS `order` (
            id          INT PRIMARY KEY,
            customer    VARCHAR(255) NOT NULL,
            inserted_at DATETIME     NOT NULL
        );
        CREATE TABLE IF NOT EXISTS order_item (
            order_id INT          NOT NULL,
            position SMALLINT     NOT NULL,
            sku      VARCHAR(32)  NOT NULL,
            PRIMARY KEY (order_id, position),
            FOREIGN KEY (order_id) REFERENCES `order`(id) ON DELETE CASCADE
        );
    """

    def transform(self, doc):
        yield "order", {
            "id":          doc["id"],
            "customer":    doc["customer"],
            "inserted_at": doc["inserted_at"],
        }
        for i, sku in enumerate(doc.get("items", [])):
            yield "order_item", {"order_id": doc["id"], "position": i, "sku": sku}
```

Then wire it into the runner:

```python
import logging
from nsq2mariadb import MariaDBConfig, Nsq2MariaDB, NsqConfig

logging.basicConfig(level=logging.INFO)

runner = Nsq2MariaDB(
    logger=logging.getLogger("nsq2mariadb"),
    mariadb_config=MariaDBConfig(
        host="mariadb", port=3306,
        user="orders", password="secret", database="orders",
    ),
    nsq_config=NsqConfig(
        address="nsq-nsqd-1", port=4150,
        channel="nsq2mariadb",
    ),
    mappers=[OrderMapper()],
)
runner.run()
```

On startup the framework opens one pymysql connection, executes every mapper's
`schema_sql` with `CREATE TABLE IF NOT EXISTS` semantics, and subscribes an
`nsq.Reader` per mapper. Each NSQ message is decoded, fanned out through the
mapper's `transform()`, and inserted in a single transaction with parameterized
`INSERT IGNORE` statements (so re-published messages are idempotent as long as
your primary key reflects content identity).

## Error handling

| Failure mode                       | Behavior                                                    |
|------------------------------------|-------------------------------------------------------------|
| JSON decode error                  | Logged with traceback, message FIN'd (dropped — won't fix). |
| `pymysql.MySQLError` during insert | Transaction rolled back, message FIN'd, traceback logged.   |
| Connection drop                    | pymysql raises, propagates, process exits — relies on container restart. |

Schema mismatches (unknown column, missing table, FK violation) are programmer
or schema bugs that loop forever if requeued, so we drop them loudly. Tune your
log shipping accordingly.

## Multiple topics per process

Pass several mappers to one `Nsq2MariaDB` instance — pynsq supports multiple
`Reader`s in one IOLoop. They share the database connection but each runs an
independent NSQ subscription. Useful when a single project produces several
related topics (e.g. `entries` + `runs`) that you want to land in the same DB.

## Releasing

Releases are auto-published to [PyPI](https://pypi.org/project/nsq2mariadb/)
by `.github/workflows/publish.yml` on every `v*` tag, via PyPI's Trusted
Publishers (OIDC — no API token stored in the repo).

To cut a release:

1. Bump the version in `setup.py`.
2. Commit and push to `main`.
3. Tag and push: `git tag v0.1.3 && git push origin v0.1.3`.

The workflow builds an sdist + wheel and publishes them under the
`pypi` GitHub environment.

## License

MIT.
