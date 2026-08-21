"""
Postgres connection wrapper that mimics the sqlite3 Connection/Cursor/Row API
the rest of the codebase already uses (conn.execute(sql, params).fetchall(),
row[0], row["col"], dict(row), cursor.rowcount) so call sites didn't need to
be rewritten beyond swapping placeholders and date functions.
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()


class Row:
    __slots__ = ("_data", "_index")

    def __init__(self, data, index):
        self._data = data
        self._index = index

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._data[self._index[key]]
        return self._data[key]

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    def keys(self):
        return self._index.keys()

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __repr__(self):
        return repr(dict(self))


class Cursor:
    def __init__(self, raw_cursor):
        self._cursor = raw_cursor
        self._index = None

    def _row_index(self):
        if self._index is None:
            self._index = {desc[0]: i for i, desc in enumerate(self._cursor.description)}
        return self._index

    def execute(self, sql, params=None):
        self._cursor.execute(sql, params)
        self._index = None
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return Row(row, self._row_index())

    def fetchall(self):
        index = self._row_index() if self._cursor.description else {}
        return [Row(r, index) for r in self._cursor.fetchall()]

    @property
    def rowcount(self):
        return self._cursor.rowcount


class Connection:
    def __init__(self, raw_conn):
        self._conn = raw_conn

    def cursor(self):
        return Cursor(self._conn.cursor())

    def execute(self, sql, params=None):
        return self.cursor().execute(sql, params)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_db():
    raw = psycopg2.connect(os.environ["DATABASE_URL"])
    return Connection(raw)
