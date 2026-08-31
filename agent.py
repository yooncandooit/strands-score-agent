"""성적 조회 에이전트.

구성 요소는 딱 3개다.
    1. 모델   — Amazon Bedrock 경유 Claude (아래 MODEL_ID로 명시 고정)
    2. 도구   — tools.py의 @tool 3개
    3. 프롬프트 — 이 에이전트가 뭐 하는 앤지 알려주는 한 문단

그리고 그 셋을 도는 루프는 Strands가 돌린다.
질문이 바뀌어도 아래 코드는 바뀌지 않는다. 바뀌는 건 모델이 고르는 도구 조합뿐이다.
"""

import os
import sys
import time

from strands import Agent
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry
from strands.models import BedrockModel

import db
from tools import aggregate, list_classes, query_scores

# ── 모델은 기본값에 기대지 않고 명시적으로 고정한다 ─────────────────────────
# 확인 방법: aws bedrock list-inference-profiles --region ap-northeast-2
#
# 서울(ap-northeast-2)에서 실호출로 확인한 결과:
#   ✅ global.anthropic.claude-sonnet-4-5-20250929-v1:0   ← 이걸 쓴다
#   ⚠️ global.anthropic.claude-haiku-4-5-20251001-v1:0    호출은 되지만 데모용으로 부적합.
#      "결석 많은 애들 빼고" 질문에서 query_scores(include_absent=False)를 부르지 않고
#      직전 rows를 직접 걸러 aggregate로 넘겨버린다(= 모델이 산수를 한다).
#      docstring을 보강해도 재현됨. 속도는 빠르지만 데모의 핵심 장면이 깨진다.
#   ❌ anthropic.claude-haiku-4-5-20251001-v1:0           접두사 없으면 on-demand 미지원
#   ❌ apac.anthropic.claude-haiku-4-5-20251001-v1:0      서울에 이 프로파일 자체가 없음
#   ❌ apac.anthropic.claude-sonnet-4-20250514-v1:0       프로파일은 있으나 액세스 미승인
# 서울에는 apac. 계열 Haiku 4.5 / Sonnet 4.5가 없다. global. 프로파일이 정답이다.
#
# (발표장 계정이 다를 때만 환경변수로 덮어쓴다. SDK 기본값에는 절대 안 기댄다.)
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID") or "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
REGION = os.environ.get("BEDROCK_REGION") or "ap-northeast-2"

# callback_handler=None이라 스트리밍 출력을 쓰지 않는다. 발표장 네트워크에서는
# 짧은 단발 요청이 더 안전해서 비스트리밍으로 고정한다. (둘 다 동작 확인함)
USE_STREAMING = False

# ── 터미널 색 (발표 화면용) ────────────────────────────────────────────────
_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


BOLD = lambda t: _c("1", t)          # noqa: E731
DIM = lambda t: _c("2", t)           # noqa: E731
CYAN = lambda t: _c("36", t)         # noqa: E731
YELLOW = lambda t: _c("33", t)       # noqa: E731
GREEN = lambda t: _c("32", t)        # noqa: E731

RULE = "─" * 72


def _fmt_arg(value) -> str:
    """도구 인자를 한 줄로 예쁘게. 긴 배열은 개수로 줄인다."""
    if isinstance(value, list):
        if len(value) > 6:
            return DIM(f"[{len(value)}개 항목]")
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    return str(value)


def _preview(text: str, width: int = 88) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width] + "…"


class ToolCallLogger(HookProvider):
    """모델이 어떤 도구를 어떤 인자로 불렀는지 터미널에 찍는다.

    이게 발표 화면이다. "모델이 스스로 골랐다"는 걸 보여주는 유일한 증거.
    """

    def __init__(self):
        self.count = 0
        self.trace: list[dict] = []
        self._index: dict[str, str] = {}  # toolUseId -> "[n] 도구이름"

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        self.count += 1
        name = event.tool_use["name"]
        args = event.tool_use.get("input") or {}
        # 모델이 도구를 여러 개 동시에 부르면 before/after 로그가 엇갈린다.
        # 결과 줄에도 번호와 이름을 같이 찍어서 짝을 알아볼 수 있게 한다.
        self._index[event.tool_use["toolUseId"]] = f"[{self.count}] {name}"
        print(f"  {CYAN('🔧')} {BOLD(f'[{self.count}] {name}')}")
        for key, value in args.items():
            print(f"       {YELLOW(key)} = {_fmt_arg(value)}")
        self.trace.append({"name": name, "input": args})

    def after_tool(self, event: AfterToolCallEvent) -> None:
        body = ""
        for block in event.result.get("content", []):
            if "text" in block:
                body += block["text"]
        took = f"{event.duration:.2f}s" if event.duration is not None else "-"
        status = event.result.get("status", "success")
        mark = GREEN("→") if status == "success" else "✗"
        label = self._index.get(event.result.get("toolUseId", ""), "")
        print(f"     {mark} {DIM(label)} {DIM(took)} {DIM(_preview(body, 74))}\n")


def build_system_prompt() -> str:
    lo, hi = db.data_range()
    return f"""당신은 영어학원 선생님을 돕는 성적 분석 조교입니다.

선생님의 질문에 답하려면 반드시 주어진 도구로 실제 데이터를 조회하세요.
기억이나 추측으로 숫자를 만들어내면 안 됩니다.

일하는 순서는 보통 이렇습니다.
1. 반 이름이나 조건("중2 반들", "월수반")이 나오면 list_classes로 반 id를 먼저 확인한다.
2. query_scores로 해당 반들의 점수를 조회한다.
3. 반끼리 비교해야 하면 조회한 rows를 aggregate에 그대로 넘긴다.
   한 반만 보면 되는 질문이면 aggregate 없이 조회 결과만으로 답해도 됩니다.

기간 해석 규칙:
- 이 데이터의 시험일 범위는 {lo} ~ {hi} 입니다.
- "이번 달", "최근" 같은 상대적 표현은 데이터 최신일({hi})이 속한 달을 기준으로 해석하세요.

답변 규칙:
- 한국어로, 선생님이 바로 읽을 수 있게 3~5줄로 짧게 답하세요.
- 숫자는 조회 결과 그대로 쓰고, 차이가 얼마나 나는지 한 줄로 짚어주세요.
- 결석/숙제 미제출 때문에 값이 달라졌다면 그 사실을 명시하세요."""


def build_agent() -> tuple[Agent, ToolCallLogger]:
    logger = ToolCallLogger()
    model = BedrockModel(
        model_id=MODEL_ID,
        region_name=REGION,
        temperature=0,
        streaming=USE_STREAMING,
    )
    agent = Agent(
        model=model,
        tools=[list_classes, query_scores, aggregate],
        system_prompt=build_system_prompt(),
        hooks=[logger],
        callback_handler=None,  # 스트리밍 기본 출력을 끄고, 툴 로그만 직접 찍는다
    )
    return agent, logger


def ask(question: str, agent: Agent = None, logger: ToolCallLogger = None) -> dict:
    """질문 하나를 던지고, 툴 호출 과정과 답변을 출력한다."""
    if agent is None:
        agent, logger = build_agent()
    logger.count = 0
    logger.trace = []

    print(f"\n{RULE}\n{BOLD('❓ ' + question)}\n{RULE}\n")

    started = time.time()
    result = agent(question)
    elapsed = time.time() - started

    answer = "".join(block.get("text", "") for block in result.message.get("content", []))
    print(f"{BOLD('💬 답변')}\n{answer.strip()}\n")

    usage = getattr(result.metrics, "accumulated_usage", None) or {}
    tokens = ""
    if usage:
        tokens = f" · 토큰 in {usage.get('inputTokens', 0):,} / out {usage.get('outputTokens', 0):,}"
    print(DIM(f"⏱ {elapsed:.1f}s · 툴 {logger.count}회{tokens}"))

    return {
        "question": question,
        "answer": answer.strip(),
        "trace": list(logger.trace),
        "elapsed": elapsed,
    }


if __name__ == "__main__":
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print("사용법: python agent.py \"3반이랑 5반, 이번 달 단어 점수 평균 비교해줘\"")
        sys.exit(1)
    print(DIM(f"model={MODEL_ID}  region={REGION}"))
    ask(question)
