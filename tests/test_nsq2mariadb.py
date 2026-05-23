#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import logging
import unittest
from unittest.mock import MagicMock

import pymysql

from nsq2mariadb.nsq2mariadb import (
    MariaDBConfig,
    Mapper,
    Nsq2MariaDB,
    NsqConfig,
    _build_insert,
    _split_statements,
)


def _make_logger():
    return logging.getLogger("test_nsq2mariadb")


def _silent_init(runner: Nsq2MariaDB) -> None:
    """Stand-in for `_register_readers` — we don't want to touch real NSQ in tests."""
    return None


class _StubCursor:
    """Records every `execute(sql, params)` call and behaves as a context manager."""

    def __init__(self):
        self.calls = []  # list of (sql, params) tuples
        self.raise_on_execute = None  # set to an Exception instance to raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if self.raise_on_execute is not None:
            raise self.raise_on_execute


class _StubConnection:
    def __init__(self):
        self.cursor_obj = _StubCursor()
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class _FakeMessage:
    def __init__(self, payload: dict):
        self.body = json.dumps(payload).encode("utf-8")


class _SingleTableMapper(Mapper):
    topic = "things"
    schema_sql = "CREATE TABLE IF NOT EXISTS thing (`id` INT PRIMARY KEY, name VARCHAR(64))"

    def transform(self, doc):
        yield "thing", {"id": doc["id"], "name": doc["name"]}


class _MultiTableMapper(Mapper):
    topic = "orders"
    schema_sql = (
        "CREATE TABLE IF NOT EXISTS `order` (`id` INT PRIMARY KEY);\n"
        "CREATE TABLE IF NOT EXISTS order_item (order_id INT, position INT, sku VARCHAR(32));"
    )

    def transform(self, doc):
        yield "order", {"id": doc["id"]}
        for i, sku in enumerate(doc.get("items", [])):
            yield "order_item", {"order_id": doc["id"], "position": i, "sku": sku}


def _build_runner(mapper, connection):
    runner = Nsq2MariaDB.__new__(Nsq2MariaDB)
    runner._logger = _make_logger()
    runner._mariadb_config = MariaDBConfig(
        host="localhost", port=3306, user="u", password="p", database="d"
    )
    runner._nsq_config = NsqConfig(address="127.0.0.1", port=4150, channel="test")
    runner._mappers = [mapper]
    runner._conn = connection
    return runner


class TestSplitStatements(unittest.TestCase):
    def test_splits_on_semicolons_and_drops_blanks(self):
        sql = "CREATE TABLE a (x INT);   ;\nCREATE TABLE b (y INT);\n\n"
        self.assertEqual(
            _split_statements(sql),
            ["CREATE TABLE a (x INT)", "CREATE TABLE b (y INT)"],
        )

    def test_empty_string(self):
        self.assertEqual(_split_statements(""), [])

    def test_single_statement_no_trailing_semicolon(self):
        self.assertEqual(_split_statements("SELECT 1"), ["SELECT 1"])


class TestBuildInsert(unittest.TestCase):
    def test_single_column(self):
        sql, params = _build_insert("t", {"a": 1})
        self.assertEqual(sql, "INSERT IGNORE INTO `t` (`a`) VALUES (%s)")
        self.assertEqual(params, (1,))

    def test_multiple_columns_preserve_dict_order(self):
        sql, params = _build_insert("zvg_entry", {"_key": "abc", "land_short": "by", "zvg_id": 7})
        self.assertEqual(
            sql,
            "INSERT IGNORE INTO `zvg_entry` (`_key`,`land_short`,`zvg_id`) VALUES (%s,%s,%s)",
        )
        self.assertEqual(params, ("abc", "by", 7))

    def test_empty_row_raises(self):
        with self.assertRaises(ValueError):
            _build_insert("t", {})


class TestHandleMessage(unittest.TestCase):
    def test_single_table_inserts_and_commits(self):
        conn = _StubConnection()
        runner = _build_runner(_SingleTableMapper(), conn)

        result = runner._handle_message(runner._mappers[0], _FakeMessage({"id": 42, "name": "x"}))

        self.assertTrue(result)
        self.assertEqual(conn.commits, 1)
        self.assertEqual(conn.rollbacks, 0)
        self.assertEqual(len(conn.cursor_obj.calls), 1)
        sql, params = conn.cursor_obj.calls[0]
        self.assertEqual(sql, "INSERT IGNORE INTO `thing` (`id`,`name`) VALUES (%s,%s)")
        self.assertEqual(params, (42, "x"))

    def test_multi_table_fanout_is_one_transaction(self):
        conn = _StubConnection()
        runner = _build_runner(_MultiTableMapper(), conn)

        result = runner._handle_message(
            runner._mappers[0],
            _FakeMessage({"id": 7, "items": ["sku-A", "sku-B", "sku-C"]}),
        )

        self.assertTrue(result)
        self.assertEqual(conn.commits, 1)  # exactly one commit for the whole fanout
        self.assertEqual(conn.rollbacks, 0)
        self.assertEqual(len(conn.cursor_obj.calls), 4)  # 1 order + 3 items
        # First call is the parent row
        sql, params = conn.cursor_obj.calls[0]
        self.assertEqual(sql, "INSERT IGNORE INTO `order` (`id`) VALUES (%s)")
        self.assertEqual(params, (7,))
        # Subsequent calls are the items with preserved order
        for i, sku in enumerate(["sku-A", "sku-B", "sku-C"]):
            sql, params = conn.cursor_obj.calls[i + 1]
            self.assertEqual(
                sql,
                "INSERT IGNORE INTO `order_item` (`order_id`,`position`,`sku`) VALUES (%s,%s,%s)",
            )
            self.assertEqual(params, (7, i, sku))

    def test_db_error_rolls_back_and_drops_message(self):
        conn = _StubConnection()
        conn.cursor_obj.raise_on_execute = pymysql.MySQLError("table missing")
        runner = _build_runner(_SingleTableMapper(), conn)

        result = runner._handle_message(runner._mappers[0], _FakeMessage({"id": 1, "name": "x"}))

        self.assertTrue(result)  # FIN — do not requeue
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 1)

    def test_json_decode_error_drops_message(self):
        conn = _StubConnection()
        runner = _build_runner(_SingleTableMapper(), conn)

        bad_message = MagicMock()
        bad_message.body = b"\xff\xfenot json"

        result = runner._handle_message(runner._mappers[0], bad_message)

        self.assertTrue(result)
        self.assertEqual(conn.commits, 0)
        self.assertEqual(conn.rollbacks, 0)
        self.assertEqual(len(conn.cursor_obj.calls), 0)


class TestApplySchemas(unittest.TestCase):
    def test_executes_each_statement_and_commits(self):
        conn = _StubConnection()
        runner = _build_runner(_MultiTableMapper(), conn)

        # Re-apply manually (the constructor isn't called in our test fixture)
        runner._apply_schemas()

        # 2 statements in _MultiTableMapper.schema_sql
        self.assertEqual(len(conn.cursor_obj.calls), 2)
        self.assertIn("CREATE TABLE IF NOT EXISTS `order`", conn.cursor_obj.calls[0][0])
        self.assertIn("CREATE TABLE IF NOT EXISTS order_item", conn.cursor_obj.calls[1][0])
        self.assertEqual(conn.commits, 1)


if __name__ == "__main__":
    unittest.main()
