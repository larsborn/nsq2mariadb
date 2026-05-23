#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generic NSQ -> MariaDB transporter.

Operators subscribe one or more `Mapper` subclasses (one per NSQ topic) to a
running `Nsq2MariaDB` instance. Each mapper declares its target schema (DDL
applied with CREATE TABLE IF NOT EXISTS on startup) and a `transform(doc)`
method that yields `(table_name, row_dict)` tuples. The framework wraps every
NSQ message in a single MariaDB transaction across all yielded rows and uses
parameterized `INSERT IGNORE` for idempotency.
"""
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

import nsq
import pymysql


@dataclass
class MariaDBConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    charset: str = "utf8mb4"


@dataclass
class NsqConfig:
    address: str
    port: int
    channel: str
    max_in_flight: int = 1


class Mapper(ABC):
    """Subclass per NSQ topic.

    Set `topic` to the NSQ topic name and `schema_sql` to one or more
    `CREATE TABLE IF NOT EXISTS` statements separated by semicolons.
    Implement `transform()` to translate a decoded JSON message into rows.
    """

    topic: str = ""
    schema_sql: str = ""

    @abstractmethod
    def transform(self, doc: dict) -> Iterable[Tuple[str, dict]]:
        """Yield `(table_name, row_dict)` per row this message should insert."""


def _split_statements(sql: str) -> List[str]:
    """Split a multi-statement SQL string on `;` and drop empty fragments."""
    return [stmt.strip() for stmt in sql.split(";") if stmt.strip()]


def _build_insert(table: str, row: dict) -> Tuple[str, Sequence]:
    """Build a parameterized `INSERT IGNORE` statement and its values tuple."""
    if not row:
        raise ValueError(f"refusing to insert empty row into {table!r}")
    columns = list(row.keys())
    col_list = ",".join(f"`{c}`" for c in columns)
    placeholders = ",".join(["%s"] * len(columns))
    sql = f"INSERT IGNORE INTO `{table}` ({col_list}) VALUES ({placeholders})"
    return sql, tuple(row[c] for c in columns)


class Nsq2MariaDB:
    """Run one or more mappers against a single MariaDB connection."""

    def __init__(
        self,
        logger: logging.Logger,
        mariadb_config: MariaDBConfig,
        nsq_config: NsqConfig,
        mappers: Sequence[Mapper],
        connection=None,
    ):
        if not mappers:
            raise ValueError("at least one Mapper is required")
        self._logger = logger
        self._mariadb_config = mariadb_config
        self._nsq_config = nsq_config
        self._mappers = list(mappers)
        self._conn = connection if connection is not None else self._open_connection()
        self._apply_schemas()
        self._register_readers()

    def run(self) -> None:
        """Enter the NSQ IOLoop. Returns when nsq.run() returns."""
        nsq.run()

    def _open_connection(self):
        cfg = self._mariadb_config
        return pymysql.connect(
            host=cfg.host,
            port=cfg.port,
            user=cfg.user,
            password=cfg.password,
            database=cfg.database,
            charset=cfg.charset,
            autocommit=False,
        )

    def _apply_schemas(self) -> None:
        for mapper in self._mappers:
            statements = _split_statements(mapper.schema_sql)
            if not statements:
                continue
            self._logger.info(
                f"applying {len(statements)} schema statement(s) for topic {mapper.topic!r}"
            )
            with self._conn.cursor() as cur:
                for stmt in statements:
                    cur.execute(stmt)
            self._conn.commit()

    def _register_readers(self) -> None:
        for mapper in self._mappers:
            nsq.Reader(
                message_handler=self._make_handler(mapper),
                nsqd_tcp_addresses=[f"{self._nsq_config.address}:{self._nsq_config.port}"],
                topic=mapper.topic,
                channel=self._nsq_config.channel,
                max_in_flight=self._nsq_config.max_in_flight,
            )
            self._logger.info(
                f"subscribed to topic {mapper.topic!r} on channel {self._nsq_config.channel!r}"
            )

    def _make_handler(self, mapper: Mapper):
        def handler(message) -> bool:
            return self._handle_message(mapper, message)

        return handler

    def _handle_message(self, mapper: Mapper, message) -> bool:
        try:
            doc = json.loads(message.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._logger.exception(
                f"failed to decode message on topic {mapper.topic!r}; dropping"
            )
            return True  # FIN; broken JSON won't fix itself on retry
        try:
            with self._conn.cursor() as cur:
                for table, row in mapper.transform(doc):
                    sql, params = _build_insert(table, row)
                    cur.execute(sql, params)
            self._conn.commit()
        except pymysql.MySQLError:
            self._conn.rollback()
            self._logger.exception(
                f"database error handling message on topic {mapper.topic!r}; dropping"
            )
            return True  # FIN; matches nsq2arangodb behavior — programmer/data bugs
            #                won't fix themselves on retry, so don't loop forever
        return True
