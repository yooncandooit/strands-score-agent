"""mock 성적 데이터를 SQLite(data/school.db)로 생성한다.

실제 Supabase 스키마(classes / students / weeks / scores)를 그대로 따르되
데이터는 전부 가짜다. 실제 개인정보는 한 건도 들어가지 않는다.

    $ python data/seed.py
"""

import json
import os
import random
import sqlite3
from datetime import date, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "school.db")

random.seed(20260831)

# 데모 기준일. "이번 달" = 2026년 8월
TODAY = date(2026, 8, 31)
WEEK_COUNT = 11  # 최근 약 2.5개월치
FIRST_MONDAY = date(2026, 6, 15)

DAY_OFFSET = {"월수": 0, "화목": 1, "금": 4}  # 주 시작(월)로부터의 시험일

ITEM_MAX = {"word": 30, "reading": 40, "mc": 30}  # 총점 100

# 반 프로필: 반별 점수/숙제율 차이를 의도적으로 크게 벌린다.
# (비교 결과가 밋밋하면 데모가 죽는다)
#
# id는 반 이름과 일부러 어긋나게 둔다("3반"의 id는 3이 아니라 103).
# 실제 Supabase도 id는 이름과 무관한 시퀀스이고, 무엇보다
# id를 추측할 수 없어야 모델이 list_classes를 먼저 부르게 된다.
CLASS_PROFILES = [
    # id, name, grade, day, time, word, reading, mc, homework_rate
    (101, "1반", "중1", "월수", "17:00", 24, 31, 24, 88),
    (102, "2반", "중1", "화목", "17:00", 20, 26, 21, 74),
    (103, "3반", "중2", "월수", "19:00", 26, 34, 26, 92),  # 중2 최상위
    (104, "4반", "중2", "화목", "19:00", 21, 27, 22, 65),  # 중2 숙제율 최저
    (105, "5반", "중2", "금", "19:00", 18, 23, 19, 80),  # 3반과 확연히 대비
    (106, "6반", "중3", "월수", "20:30", 25, 33, 25, 85),
    (107, "7반", "중3", "화목", "20:30", 22, 29, 23, 78),
]

SURNAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신", "권"]
GIVEN = [
    "가온", "나래", "다올", "라온", "미르", "바다", "새롬", "아람", "여울", "이든",
    "하람", "차온", "지호", "윤슬", "해든", "누리", "도담", "은결", "한별", "슬기",
]

SCHEMA = """
DROP TABLE IF EXISTS scores;
DROP TABLE IF EXISTS weeks;
DROP TABLE IF EXISTS students;
DROP TABLE IF EXISTS classes;

CREATE TABLE classes (
    id      INTEGER PRIMARY KEY,
    name    TEXT NOT NULL UNIQUE,
    day     TEXT NOT NULL,
    time    TEXT,
    grade   TEXT
);

CREATE TABLE students (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    pin           TEXT NOT NULL,
    class_id      INTEGER REFERENCES classes(id),
    is_active     INTEGER DEFAULT 1,
    phone         TEXT,
    student_phone TEXT
);

CREATE TABLE weeks (
    id           INTEGER PRIMARY KEY,
    class_id     INTEGER REFERENCES classes(id),
    test_date    TEXT NOT NULL,
    label        TEXT,
    score_config TEXT,
    item_config  TEXT
);

CREATE TABLE scores (
    id            INTEGER PRIMARY KEY,
    student_id    INTEGER REFERENCES students(id),
    week_id       INTEGER REFERENCES weeks(id),
    word_score    REAL DEFAULT 0,
    reading_score REAL DEFAULT 0,
    mc_score      REAL DEFAULT 0,
    total_score   REAL,
    homework_rate INTEGER DEFAULT 0,
    attendance    INTEGER DEFAULT 1,
    no_homework   INTEGER DEFAULT 0,
    clinic_target INTEGER DEFAULT 0,
    item_scores   TEXT
);

CREATE INDEX idx_scores_week ON scores(week_id);
CREATE INDEX idx_scores_student ON scores(student_id);
CREATE INDEX idx_weeks_class ON weeks(class_id);
CREATE INDEX idx_students_class ON students(class_id);
"""

ITEM_CONFIG = json.dumps(
    [
        {"key": "word", "label": "단어", "max": ITEM_MAX["word"]},
        {"key": "reading", "label": "독해", "max": ITEM_MAX["reading"]},
        {"key": "mc", "label": "객관식", "max": ITEM_MAX["mc"]},
    ],
    ensure_ascii=False,
)
SCORE_CONFIG = json.dumps({"total": 100, "pass_line": 60}, ensure_ascii=False)


def _clamp(value, lo, hi):
    return max(lo, min(hi, value))


def _make_names(count, used):
    names = []
    while len(names) < count:
        name = random.choice(SURNAMES) + random.choice(GIVEN)
        if name in used:
            continue
        used.add(name)
        names.append(name)
    return names


def build():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)

    classes = [(c[0], c[1], c[3], c[4], c[2]) for c in CLASS_PROFILES]
    conn.executemany("INSERT INTO classes (id, name, day, time, grade) VALUES (?,?,?,?,?)", classes)

    used_names = set()
    students = []       # (id, name, pin, class_id, is_active, phone, student_phone)
    student_meta = {}   # student_id -> {ability, hw_offset, absent_prone}
    sid = 1
    for cls in CLASS_PROFILES:
        class_id = cls[0]
        headcount = random.randint(8, 12)
        names = _make_names(headcount, used_names)
        # 반마다 "결석이 잦은 학생" 2명을 지정한다. 데모 ②가 값 차이를 만들어야 하므로.
        absent_prone = set(random.sample(range(headcount), 2))
        for idx, name in enumerate(names):
            students.append(
                (
                    sid,
                    name,
                    f"{random.randint(1000, 9999)}",
                    class_id,
                    1,
                    f"010-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
                    f"010-{random.randint(1000, 9999)}-{random.randint(1000, 9999)}",
                )
            )
            student_meta[sid] = {
                "class_id": class_id,
                "ability": random.gauss(0, 0.10),
                "hw_offset": random.gauss(0, 6),
                "absent_prone": idx in absent_prone,
            }
            sid += 1
    conn.executemany(
        "INSERT INTO students (id, name, pin, class_id, is_active, phone, student_phone) VALUES (?,?,?,?,?,?,?)",
        students,
    )

    weeks = []
    week_id = 1
    for cls in CLASS_PROFILES:
        class_id, _, _, day = cls[0], cls[1], cls[2], cls[3]
        for n in range(WEEK_COUNT):
            monday = FIRST_MONDAY + timedelta(weeks=n)
            test_date = monday + timedelta(days=DAY_OFFSET[day])
            weeks.append(
                (
                    week_id,
                    class_id,
                    test_date.isoformat(),
                    f"{test_date.month}월 {n + 1}주차",
                    SCORE_CONFIG,
                    ITEM_CONFIG,
                )
            )
            week_id += 1
    conn.executemany(
        "INSERT INTO weeks (id, class_id, test_date, label, score_config, item_config) VALUES (?,?,?,?,?,?)",
        weeks,
    )

    profile_by_class = {c[0]: c for c in CLASS_PROFILES}
    students_by_class = {}
    for s_id, meta in student_meta.items():
        students_by_class.setdefault(meta["class_id"], []).append(s_id)

    scores = []
    score_id = 1
    for week in weeks:
        w_id, class_id = week[0], week[1]
        prof = profile_by_class[class_id]
        base = {"word": prof[5], "reading": prof[6], "mc": prof[7]}
        hw_base = prof[8]

        for s_id in students_by_class[class_id]:
            meta = student_meta[s_id]
            absent_rate = 0.30 if meta["absent_prone"] else 0.03
            attended = random.random() > absent_rate

            if attended:
                item = {}
                for key, mean in base.items():
                    raw = mean * (1 + meta["ability"]) + random.gauss(0, ITEM_MAX[key] * 0.07)
                    item[key] = round(_clamp(raw, 0, ITEM_MAX[key]), 1)
                # 숙제율이 낮은 반일수록 미제출이 잦다
                no_homework = random.random() < (100 - hw_base) / 220
                if no_homework:
                    homework_rate = 0
                else:
                    homework_rate = int(_clamp(round(hw_base + meta["hw_offset"] + random.gauss(0, 5)), 0, 100))
            else:
                # 결석하면 시험을 못 봤으니 0점 처리 (실제 운영과 동일)
                item = {"word": 0.0, "reading": 0.0, "mc": 0.0}
                no_homework = True
                homework_rate = 0

            total = round(item["word"] + item["reading"] + item["mc"], 1)
            scores.append(
                (
                    score_id,
                    s_id,
                    w_id,
                    item["word"],
                    item["reading"],
                    item["mc"],
                    total,
                    homework_rate,
                    1 if attended else 0,
                    1 if no_homework else 0,
                    1 if (attended and total < 60) else 0,
                    json.dumps({"단어": item["word"], "독해": item["reading"], "객관식": item["mc"]}, ensure_ascii=False),
                )
            )
            score_id += 1

    conn.executemany(
        """INSERT INTO scores
           (id, student_id, week_id, word_score, reading_score, mc_score, total_score,
            homework_rate, attendance, no_homework, clinic_target, item_scores)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        scores,
    )
    conn.commit()
    return conn, len(classes), len(students), len(weeks), len(scores)


def report(conn):
    print(f"\nDB: {DB_PATH}")
    print(f"기준일: {TODAY.isoformat()}  |  주차 범위: {FIRST_MONDAY.isoformat()} ~ {WEEK_COUNT}주\n")

    rows = conn.execute(
        """
        SELECT c.name, c.grade, c.day,
               COUNT(DISTINCT s.id)                                    AS 학생수,
               ROUND(AVG(sc.total_score), 1)                           AS 전체평균,
               ROUND(AVG(CASE WHEN sc.attendance=1 THEN sc.total_score END), 1) AS 출석만평균,
               ROUND(AVG(sc.word_score), 1)                            AS 단어평균,
               ROUND(AVG(sc.homework_rate), 1)                         AS 숙제율,
               SUM(CASE WHEN sc.attendance=0 THEN 1 ELSE 0 END)        AS 결석건,
               SUM(CASE WHEN sc.no_homework=1 THEN 1 ELSE 0 END)       AS 숙제미제출
        FROM classes c
        JOIN students s ON s.class_id = c.id
        JOIN scores  sc ON sc.student_id = s.id
        GROUP BY c.id ORDER BY c.id
        """
    ).fetchall()

    header = ["반", "학년", "요일", "학생", "전체평균", "출석만", "단어", "숙제율", "결석", "미제출"]
    print("  ".join(f"{h:>6}" for h in header))
    for r in rows:
        print("  ".join(f"{str(v):>6}" for v in r))


if __name__ == "__main__":
    conn, n_c, n_s, n_w, n_sc = build()
    print(f"생성 완료: classes={n_c}, students={n_s}, weeks={n_w}, scores={n_sc}")
    report(conn)
    conn.close()
