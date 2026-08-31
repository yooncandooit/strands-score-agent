"""에이전트가 쓰는 도구 3개.

이 파일의 핵심은 코드가 아니라 **docstring**이다.
Strands에서 모델은 함수 본문을 보지 못한다. 함수 이름, 타입힌트, 그리고
docstring만 읽고 "지금 어떤 도구를 어떤 인자로 부를지"를 정한다.
docstring이 곧 API 명세이자 사용설명서다.

도구는 3개뿐이고, 질문이 바뀌어도 이 파일은 바뀌지 않는다.
바뀌는 것은 모델이 고르는 '조합'이다.
"""

import json

from strands import tool

import db

# 집계 가능한 지표 -> scores 테이블 컬럼
METRICS = {
    "total": "total_score",
    "word": "word_score",
    "reading": "reading_score",
    "mc": "mc_score",
    "homework_rate": "homework_rate",
}

METRIC_LABEL = {
    "total": "총점",
    "word": "단어",
    "reading": "독해",
    "mc": "객관식",
    "homework_rate": "숙제율",
}

GROUP_FIELD = {"class": "class_name", "grade": "grade", "day": "day"}


def _json(payload) -> str:
    return json.dumps(payload, ensure_ascii=False)


@tool
def list_classes(grade: str = None, day: str = None) -> str:
    """학원의 반 목록을 조회합니다.

    반 이름("3반")만 알고 반 id를 모를 때, 또는 "중2 반들", "월수반" 처럼
    조건에 맞는 반들을 한번에 찾을 때 가장 먼저 사용하세요.
    여기서 얻은 id 목록을 query_scores의 class_ids 인자로 넘기면 됩니다.

    Args:
        grade: 학년으로 필터링. "중1" | "중2" | "중3" 중 하나. 생략하면 전체 학년.
        day: 수업 요일로 필터링. "월수" | "화목" | "금" 중 하나. 생략하면 전체 요일.

    Returns:
        반 목록 JSON. 각 항목은 id(반 번호), name(반 이름), grade(학년),
        day(수업 요일), time(수업 시간), student_count(재원 학생 수)를 가집니다.
    """
    sql = """
        SELECT c.id, c.name, c.grade, c.day, c.time,
               COUNT(s.id) AS student_count
        FROM classes c
        LEFT JOIN students s ON s.class_id = c.id AND s.is_active = 1
        WHERE 1=1
    """
    params: list = []
    if grade:
        sql += " AND c.grade = ?"
        params.append(grade)
    if day:
        sql += " AND c.day = ?"
        params.append(day)
    sql += " GROUP BY c.id ORDER BY c.id"

    rows = db.query(sql, tuple(params))
    return _json({"count": len(rows), "classes": rows})


@tool
def query_scores(
    class_ids: list[int] = None,
    date_from: str = None,
    date_to: str = None,
    include_absent: bool = True,
) -> str:
    """주차 시험 점수를 조회합니다. 학생 한 명당 한 줄로, 기간 내 성적을 평균 내어 돌려줍니다.

    반 목록(class_ids), 시험 기간(date_from~date_to), 결석 포함 여부로 필터링합니다.
    조회 결과(rows)를 그대로 aggregate 도구에 넘기면 반별/학년별/요일별 집계가 됩니다.

    Args:
        class_ids: 조회할 반 id 목록. 예: [103, 105]. 생략하면 전 반을 조회합니다.
            반 id는 반 이름("3반")과 다릅니다. 반드시 list_classes로 먼저 확인하고,
            거기서 받은 id를 그대로 넣으세요. 이름에서 id를 추측하지 마세요.
        date_from: 시험일 시작(포함). "YYYY-MM-DD" 형식. 예: "2026-08-01".
            생략하면 가장 오래된 시험부터입니다.
        date_to: 시험일 종료(포함). "YYYY-MM-DD" 형식. 예: "2026-08-31".
            생략하면 가장 최근 시험까지입니다.
        include_absent: True(기본)면 결석한 회차도 0점으로 포함해 평균을 냅니다.
            False면 결석한 회차를 아예 빼고 응시한 회차만으로 평균을 냅니다.
            "결석한 애들 빼고", "결석 많은 애들 제외하고", "결석 빼고 다시" 같은 요청은
            전부 include_absent=False로 이 도구를 다시 호출해서 처리하세요.
            이미 받아둔 결과에서 결석자를 직접 골라내 계산하면 안 됩니다.
            그건 회차 단위 결석을 반영하지 못해서 값이 틀립니다.

    Returns:
        학생별 성적 JSON. 각 행은 student(학생 이름), class_id, class_name(반 이름),
        grade(학년), day(요일), word/reading/mc(단어·독해·객관식 평균),
        total(총점 평균), homework_rate(숙제율 평균),
        sessions(평균에 쓰인 회차 수), absent_sessions(기간 내 결석 회차 수)를 가집니다.
        summary에는 조회 조건과 전체 평균이 함께 담깁니다.
    """
    sql = """
        SELECT s.id AS student_id, s.name AS student,
               c.id AS class_id, c.name AS class_name, c.grade, c.day,
               ROUND(AVG(sc.word_score), 1)    AS word,
               ROUND(AVG(sc.reading_score), 1) AS reading,
               ROUND(AVG(sc.mc_score), 1)      AS mc,
               ROUND(AVG(sc.total_score), 1)   AS total,
               ROUND(AVG(sc.homework_rate), 1) AS homework_rate,
               COUNT(sc.id) AS sessions
        FROM scores sc
        JOIN students s ON s.id = sc.student_id
        JOIN weeks   w ON w.id = sc.week_id
        JOIN classes c ON c.id = s.class_id
        WHERE s.is_active = 1
    """
    params: list = []
    if class_ids:
        sql += f" AND c.id IN ({','.join('?' * len(class_ids))})"
        params.extend(class_ids)
    if date_from:
        sql += " AND w.test_date >= ?"
        params.append(date_from)
    if date_to:
        sql += " AND w.test_date <= ?"
        params.append(date_to)
    if not include_absent:
        sql += " AND sc.attendance = 1"
    sql += " GROUP BY s.id ORDER BY c.id, s.name"

    rows = db.query(sql, tuple(params))

    # 기간 내 결석 회차 수는 별도로 센다 (include_absent=False 여도 몇 번 빠졌는지는 알려준다)
    absent_sql = """
        SELECT s.id AS sid, SUM(CASE WHEN sc.attendance = 0 THEN 1 ELSE 0 END) AS absent_sessions
        FROM scores sc
        JOIN students s ON s.id = sc.student_id
        JOIN weeks   w ON w.id = sc.week_id
        WHERE s.is_active = 1
    """
    absent_params: list = []
    if class_ids:
        absent_sql += f" AND s.class_id IN ({','.join('?' * len(class_ids))})"
        absent_params.extend(class_ids)
    if date_from:
        absent_sql += " AND w.test_date >= ?"
        absent_params.append(date_from)
    if date_to:
        absent_sql += " AND w.test_date <= ?"
        absent_params.append(date_to)
    absent_sql += " GROUP BY s.id"

    absent_by_student = {r["sid"]: r["absent_sessions"] for r in db.query(absent_sql, tuple(absent_params))}

    for row in rows:
        row["absent_sessions"] = absent_by_student.get(row["student_id"], 0)

    overall = round(sum(r["total"] for r in rows) / len(rows), 1) if rows else None
    return _json(
        {
            "summary": {
                "class_ids": class_ids or "전체",
                "date_from": date_from or "전체",
                "date_to": date_to or "전체",
                "include_absent": include_absent,
                "student_count": len(rows),
                "overall_total_avg": overall,
            },
            "rows": rows,
        }
    )


@tool
def aggregate(rows: list, group_by: str, metric: str) -> str:
    """query_scores로 조회한 학생별 성적을 그룹별로 묶어 평균을 냅니다.

    반끼리 비교하거나, 학년별·요일별로 묶어서 볼 때 사용합니다.
    결과는 평균이 높은 순으로 정렬되며, 1등과 꼴찌의 차이(gap)도 함께 알려줍니다.

    Args:
        rows: query_scores가 반환한 rows 배열을 **그대로** 넣으세요.
            일부 학생만 골라내거나 직접 편집한 배열을 넣으면 안 됩니다.
            조건이 바뀌었다면 query_scores를 그 조건으로 다시 호출해서 새 rows를 받으세요.
        group_by: 묶는 기준. "class"(반별) | "grade"(학년별) | "day"(요일별) 중 하나.
        metric: 집계할 지표. "total"(총점) | "word"(단어) | "reading"(독해) |
            "mc"(객관식) | "homework_rate"(숙제율) 중 하나.

    Returns:
        그룹별 집계 JSON. 각 항목은 group(그룹 이름), avg(평균),
        students(학생 수), min/max(그룹 내 최저·최고)를 가집니다.
        평균 내림차순 정렬이므로 첫 항목이 1위, 마지막 항목이 꼴찌입니다.
    """
    if group_by not in GROUP_FIELD:
        return _json({"error": f"group_by는 {list(GROUP_FIELD)} 중 하나여야 합니다. 받은 값: {group_by}"})
    if metric not in METRICS:
        return _json({"error": f"metric은 {list(METRICS)} 중 하나여야 합니다. 받은 값: {metric}"})
    if not rows:
        return _json({"error": "rows가 비어 있습니다. query_scores로 먼저 데이터를 조회하세요."})

    field = GROUP_FIELD[group_by]
    buckets: dict[str, list[float]] = {}
    for row in rows:
        key = row.get(field)
        value = row.get(metric)
        if key is None or value is None:
            continue
        buckets.setdefault(str(key), []).append(float(value))

    if not buckets:
        return _json(
            {"error": f"rows에 '{field}' 또는 '{metric}' 필드가 없습니다. query_scores 결과를 그대로 넘겼는지 확인하세요."}
        )

    groups = [
        {
            "group": key,
            "avg": round(sum(vals) / len(vals), 1),
            "students": len(vals),
            "min": round(min(vals), 1),
            "max": round(max(vals), 1),
        }
        for key, vals in buckets.items()
    ]
    groups.sort(key=lambda g: g["avg"], reverse=True)

    return _json(
        {
            "group_by": group_by,
            "metric": metric,
            "metric_label": METRIC_LABEL[metric],
            "groups": groups,
            "gap": round(groups[0]["avg"] - groups[-1]["avg"], 1) if len(groups) > 1 else 0,
        }
    )


if __name__ == "__main__":
    # 도구 단독 실행 테스트 (에이전트 없이, 사람이 직접 호출)
    print("--- list_classes(grade='중2') ---")
    print(list_classes(grade="중2"))

    print("\n--- query_scores(class_ids=[103], date_from='2026-08-01') 결석 포함 ---")
    inc = json.loads(query_scores(class_ids=[103], date_from="2026-08-01"))
    print(_json(inc["summary"]))

    print("\n--- 같은 조건, 결석 제외 ---")
    exc = json.loads(query_scores(class_ids=[103], date_from="2026-08-01", include_absent=False))
    print(_json(exc["summary"]))

    print("\n--- aggregate(반별, 총점) ---")
    print(aggregate(rows=inc["rows"], group_by="class", metric="total"))
