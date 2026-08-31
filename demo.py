"""데모: 질문 3개를 같은 에이전트에 순서대로 던진다.

증명하려는 것은 하나다.
    질문이 바뀌어도 tools.py / agent.py 는 한 줄도 바뀌지 않는다.
    바뀌는 건 모델이 고르는 도구의 순서와 인자뿐이다.

    $ python demo.py          # 3개 전부
    $ python demo.py 2        # 2번만
"""

import sys

from agent import BOLD, DIM, MODEL_ID, REGION, RULE, ask, build_agent

QUESTIONS = [
    # ① 화면으로 이미 만들어 둔 질문 — 에이전트도 당연히 된다
    ("화면에 있던 것", "3반이랑 5반, 이번 달 단어 점수 평균 비교해줘"),
    # ② 화면으로 안 만든 변형 질문 — 여기가 하이라이트
    ("화면에 없던 것", "결석 많은 애들 빼고 3반 평균 다시 내줘"),
    # ③ 또 다른 조합 — 코드가 안 바뀐다는 걸 못박는다
    ("또 다른 조합", "중2 반들 중에 숙제율 제일 낮은 반이 어디야?"),
]


def print_trace_summary(results):
    print(f"\n{RULE}\n{BOLD('📋 툴 호출 비교 — 질문마다 조합이 달라진다')}\n{RULE}")
    for i, r in enumerate(results, 1):
        label = r["label"]
        chain = " → ".join(t["name"] for t in r["trace"]) or "(툴 호출 없음)"
        print(f"\n  {BOLD(f'{i}. {label}')}  {DIM(r['question'])}")
        print(f"     {chain}")
        for t in r["trace"]:
            args = ", ".join(
                f"{k}={'[%d개]' % len(v) if isinstance(v, list) and len(v) > 6 else v!r}"
                for k, v in (t["input"] or {}).items()
            )
            print(DIM(f"       · {t['name']}({args})"))
    print(f"\n{RULE}")
    print(BOLD("  이 3개를 돌리는 동안 tools.py 와 agent.py 는 단 한 줄도 바뀌지 않았습니다."))
    print(f"{RULE}\n")


def main():
    picked = sys.argv[1:]
    questions = QUESTIONS
    if picked:
        idx = [int(p) - 1 for p in picked if p.isdigit()]
        questions = [QUESTIONS[i] for i in idx if 0 <= i < len(QUESTIONS)]

    print(DIM(f"model={MODEL_ID}  region={REGION}  tools=3"))

    agent, logger = build_agent()
    results = []
    for label, question in questions:
        out = ask(question, agent=agent, logger=logger)
        out["label"] = label
        results.append(out)

    print_trace_summary(results)


if __name__ == "__main__":
    main()
