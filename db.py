"""SQLite 조회 헬퍼.

실제 시스템에서는 이 자리에 admin-api(Deno Edge Function) 호출이 들어간다.
실습에서는 같은 스키마의 로컬 mock DB를 읽는다. 도구(tools.py) 입장에서는
"데이터를 어디서 가져오는지"만 다를 뿐 하는 일은 같다.
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "school.db")


def connect() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise FileNotFoundError(f"{DB_PATH} 가 없습니다. 먼저 `python data/seed.py` 를 실행하세요.")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: tuple = ()) -> list[dict]:
    """SELECT 결과를 dict 리스트로 반환한다."""
    with connect() as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def data_range() -> tuple[str, str]:
    """데이터에 존재하는 시험일의 (최초, 최종)을 반환한다."""
    row = query("SELECT MIN(test_date) AS lo, MAX(test_date) AS hi FROM weeks")[0]
    return row["lo"], row["hi"]
