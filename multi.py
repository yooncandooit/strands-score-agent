"""multi.py — 멀티에이전트 패턴 4종을 실행·비교한다.

tools.py의 @tool 3개(list_classes / query_scores / aggregate)는 **한 줄도 바뀌지 않는다.**
바뀌는 건 그 도구들을 쥔 에이전트를 "어떻게 묶느냐" 뿐이다.

    --pattern tools   Agents-as-Tools   묶는 사람: 모델 (오케스트레이터가 고른다)
    --pattern graph   Graph 병렬        묶는 사람: 개발자 (엣지를 내가 그린다)
    --pattern route   Graph 조건부      묶는 사람: 개발자 (+ 발송 경로엔 사람 승인)
    --pattern swarm   Swarm 자율협업     묶는 사람: 에이전트 (그래서 안 쓴다)

사용법:
    python multi.py --pattern tools
    python multi.py --pattern tools -q "3반 평균만 알려줘"
    python multi.py --pattern graph
    python multi.py --pattern route -q "3반 학부모님께 문자 보내줘"
    python multi.py --pattern swarm
"""

import argparse
import os
import sys
import threading
import time
from pathlib import Path

from strands import Agent, tool
from strands.hooks import (
    AfterNodeCallEvent,
    AfterToolCallEvent,
    BeforeNodeCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)
from strands.models import BedrockModel
from strands.multiagent import GraphBuilder, Swarm

import db
from tools import aggregate, list_classes, query_scores

# ── 모델 ────────────────────────────────────────────────────────────────────
# agent.py와 같은 모델을 쓴다. 서울 리전에는 us./apac. 계열 Sonnet 4.5가 없어서
# global. 추론 프로파일을 쓴다. SDK 기본값에는 기대지 않고 항상 명시한다.
MODEL_ID = os.environ.get("BEDROCK_MODEL_ID") or "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
REGION = os.environ.get("BEDROCK_REGION") or "ap-northeast-2"

# 모든 에이전트가 이 객체 하나를 공유한다. (워크샵 예제처럼 model="us.anthropic..."
# 문자열을 넘기면 리전·temperature를 못 박을 수 없다.)
MODEL = BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0, streaming=False)

OUT_DIR = Path(__file__).resolve().parent

# ── 터미널 색 (발표 화면용) ──────────────────────────────────────────────────
_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


BOLD = lambda t: _c("1", t)      # noqa: E731
DIM = lambda t: _c("2", t)       # noqa: E731
CYAN = lambda t: _c("36", t)     # noqa: E731
YELLOW = lambda t: _c("33", t)   # noqa: E731
GREEN = lambda t: _c("32", t)    # noqa: E731
MAGENTA = lambda t: _c("35", t)  # noqa: E731

BAR = "=" * 68
RULE = "-" * 68


def _fmt_arg(value) -> str:
    """도구 인자를 한 줄로. 긴 값은 줄인다.

    Swarm의 handoff_to_agent는 context에 학생 전원 데이터를 통째로 실어 보내서
    안 줄이면 로그 한 줄이 화면을 다 먹는다.
    """
    if isinstance(value, dict):
        return "{" + ", ".join(list(value)[:4]) + (", …}" if len(value) > 4 else "}")
    if isinstance(value, list):
        return f"[{len(value)}개]" if len(value) > 6 else str(value)
    if isinstance(value, str):
        one = " ".join(value.split())
        return f'"{one[:40]}…"' if len(one) > 40 else f'"{one}"'
    return str(value)


def _preview(text, width: int = 70) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width] + "…"


# ── 실행 집계 (여러 에이전트에 흩어진 토큰/시간을 한 곳에 모은다) ──────────────
class Run:
    """한 번의 실행에서 벌어진 일을 전부 모아두는 곳. 푸터 출력의 재료."""

    def __init__(self):
        self.lock = threading.Lock()
        self.input_tokens = 0
        self.output_tokens = 0
        self.tool_calls: list[str] = []      # 실제로 불린 도구/에이전트 이름 순서대로
        self.agents_called: list[str] = []   # 실제로 돌아간 전문 에이전트
        self.spans: list[tuple[str, float, float]] = []  # (노드명, 시작, 끝) — 병렬 판정용

    def add_usage(self, usage) -> None:
        if not usage:
            return
        with self.lock:
            self.input_tokens += usage.get("inputTokens", 0)
            self.output_tokens += usage.get("outputTokens", 0)

    def add_agent_result(self, result) -> None:
        self.add_usage(getattr(getattr(result, "metrics", None), "accumulated_usage", None))

    def note_agent(self, name: str) -> None:
        with self.lock:
            self.agents_called.append(name)

    def note_span(self, name: str, started: float, ended: float) -> None:
        with self.lock:
            self.spans.append((name, started, ended))

    def parallel_pairs(self) -> list[tuple[str, str, float]]:
        """시간대가 겹친 노드 쌍과 겹친 시간(초). 병렬 실행의 증거."""
        pairs = []
        for i, (n1, s1, e1) in enumerate(self.spans):
            for n2, s2, e2 in self.spans[i + 1:]:
                overlap = min(e1, e2) - max(s1, s2)
                if overlap > 0:
                    pairs.append((n1, n2, overlap))
        return pairs


RUN = Run()


# ── 훅: 누가 무슨 도구를 어떤 인자로 불렀나 ──────────────────────────────────
class ToolCallLogger(HookProvider):
    """도구 호출을 들여쓰기로 계층 표현해서 찍는다. 이게 발표 화면이다."""

    def __init__(self, indent: int = 3, owner: str = "", mark: str = "🔧"):
        self.pad = " " * indent
        self.owner = owner
        self.mark = mark
        self._names: dict[str, str] = {}

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use["name"]
        args = event.tool_use.get("input") or {}
        self._names[event.tool_use["toolUseId"]] = name
        with RUN.lock:
            RUN.tool_calls.append(name)
        tag = DIM(f"({self.owner})") + " " if self.owner else ""
        shown = "  ".join(f"{YELLOW(k)}={_fmt_arg(v)}" for k, v in args.items())
        print(f"{self.pad}{self.mark} {tag}{BOLD(name)}  {shown}".rstrip())

    def after_tool(self, event: AfterToolCallEvent) -> None:
        body = "".join(b.get("text", "") for b in event.result.get("content", []) if "text" in b)
        took = f"{event.duration:.1f}s" if event.duration is not None else "-"
        print(f"{self.pad}  {GREEN('↩')} {DIM(_preview(body))} {DIM(took)}")


class NodeCallLogger(HookProvider):
    """Graph/Swarm의 노드 실행 시작·종료를 찍는다.

    시작/종료 시각을 함께 기록해서 '진짜 병렬로 돌았는지'를 나중에 숫자로 증명한다.
    """

    def __init__(self):
        self.started: dict[str, float] = {}
        self.order: list[str] = []

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeNodeCallEvent, self.before_node)
        registry.add_callback(AfterNodeCallEvent, self.after_node)

    def before_node(self, event: BeforeNodeCallEvent) -> None:
        now = time.time()
        self.started[event.node_id] = now
        self.order.append(event.node_id)
        RUN.note_agent(event.node_id)
        print(f"\n{MAGENTA('▶ 노드 시작')} {BOLD(event.node_id)} {DIM(f'+{now - T0:.1f}s')}")

    def after_node(self, event: AfterNodeCallEvent) -> None:
        now = time.time()
        started = self.started.get(event.node_id, now)
        RUN.note_span(event.node_id, started, now)
        print(f"{MAGENTA('■ 노드 종료')} {BOLD(event.node_id)} "
              f"{DIM(f'+{now - T0:.1f}s (걸린 시간 {now - started:.1f}s)')}")


T0 = time.time()  # 실행 기준 시각. main에서 다시 세팅한다.


# ── 파일 저장 도구 ──────────────────────────────────────────────────────────
# strands_tools의 file_write를 쓰지 않는다. 새 의존성 없이 여기서 두 줄로 만든다.
# "@tool은 결국 그냥 파이썬 함수"라는 발표 메시지와도 맞는다.
def _save(filename: str, content: str) -> str:
    path = OUT_DIR / filename
    path.write_text(content, encoding="utf-8")
    return f"{filename} 저장 완료 ({len(content)}자)"


@tool
def save_report(content: str) -> str:
    """작성한 마크다운 리포트를 report.md 파일로 저장합니다.

    Args:
        content: 저장할 마크다운 전문. 표와 제목을 포함한 완성된 문서를 넣으세요.

    Returns:
        저장 결과 메시지.
    """
    return _save("report.md", content)


@tool
def save_message(content: str) -> str:
    """작성한 학부모 발송용 문자 초안을 message.md 파일로 저장합니다.

    Args:
        content: 저장할 문자 초안 전문. 200자 이내의 존댓말 본문을 넣으세요.

    Returns:
        저장 결과 메시지.
    """
    return _save("message.md", content)


# ── 전문 에이전트 3종 ───────────────────────────────────────────────────────
DATA_LO, DATA_HI = db.data_range()

SCORE_QUERY_PROMPT = f"""당신은 영어학원 성적 데이터를 조회하는 조회 전담 에이전트입니다.

반드시 지킬 순서:
1. 반 이름("3반")과 반 id는 **다릅니다.** 어떤 반을 조회하든 먼저 list_classes로 id를 확인하세요.
   이름에서 id를 추측하면 안 됩니다.
2. 그 id를 query_scores의 class_ids에 넣어 점수를 조회합니다.
3. 반끼리 비교해야 하면 query_scores가 준 rows를 그대로 aggregate에 넘깁니다.
   한 반만 보면 되는 질문이면 aggregate 없이 답해도 됩니다.

기간 해석:
- 데이터의 시험일 범위는 {DATA_LO} ~ {DATA_HI} 입니다.
- "이번 달", "최근"은 데이터 최신일({DATA_HI})이 속한 달(=2026-08-01~2026-08-31)로 해석하세요.

절대 규칙:
- 숫자를 지어내지 마세요. 도구가 돌려준 값만 씁니다.
- "결석 빼고", "결석 많은 애들 제외"는 query_scores(include_absent=False)로 **다시 조회**해서 처리합니다.
  이미 받은 결과를 직접 걸러내면 안 됩니다.

답변 형식(중요): 다음 에이전트가 그대로 받아 쓸 수 있게, 조회한 **숫자를 빠짐없이** 적으세요.
- 반 이름과 반 id, 조회 기간, 학생 수
- 반 평균(총점/단어/독해/객관식), 숙제율 평균
- 학생별 총점 목록 (상위 3명, 하위 3명은 반드시 포함)
- 결석 회차가 있는 학생이 있으면 그 사실
"""

REPORT_PROMPT = """당신은 학원 원장에게 보고할 반별 성적 리포트를 쓰는 에이전트입니다.

**데이터를 새로 조회하지 마세요.** 당신에게는 조회 도구가 없습니다.
앞 단계에서 전달받은 내용만 사용합니다. 전달받지 않은 숫자는 절대 지어내지 마세요.

리포트에 반드시 넣을 것:
1. 제목과 조회 기간 한 줄
2. **마크다운 표**로 반 요약: 반 이름 / 학생 수 / 총점 평균 / 단어·독해·객관식 평균 / 숙제율
3. **마크다운 표**로 상위 3명, 하위 3명 (이름과 총점)
4. 숙제율과 결석에 대한 코멘트 2~3줄
5. 다음 주 지도 제안 2가지

완성한 마크다운 전문을 save_report 도구로 저장하고,
마지막에 저장 결과와 리포트 핵심 3줄을 요약해 답하세요.
"""

MESSAGE_PROMPT = """당신은 학부모에게 보낼 성적 안내 문자 **초안**을 쓰는 에이전트입니다.

⚠️ 당신은 초안만 만듭니다. **실제 발송 기능은 없습니다.** 발송했다고 말하지 마세요.

**데이터를 새로 조회하지 마세요.** 앞 단계에서 전달받은 내용만 사용합니다.

문자 작성 규칙:
- 200자 이내. 존댓말. 학부모가 읽는다는 전제로 씁니다.
- **개별 학생의 실명을 넣지 마세요.** 반 단위 이야기만 합니다.
- 반 평균과 숙제율을 한 문장씩 담고, 마지막은 감사 인사로 맺습니다.
- 등수나 하위권 학생을 특정하는 표현은 쓰지 않습니다.
- 성적 숫자를 전달받지 못했다면 지어내지 말고 [반 평균], [숙제율]처럼
  **대괄호 빈칸으로 남긴 초안**을 만드세요. 선생님이 채워 넣을 자리입니다.

완성한 문자 초안을 save_message 도구로 저장하고,
마지막에 저장 결과와 문자 본문을 그대로 답하세요.
"""


def score_query_agent(logger_indent: int = 6, owner: str = "") -> Agent:
    return Agent(
        model=MODEL,
        tools=[list_classes, query_scores, aggregate],
        system_prompt=SCORE_QUERY_PROMPT,
        hooks=[ToolCallLogger(indent=logger_indent, owner=owner, mark="└ 🔧")],
        callback_handler=None,
        name="score_query",
        # description은 Swarm 전용이다. Swarm은 다른 에이전트를 이 문장으로만 파악한다
        # (_build_node_input이 "Agent name: X. Agent description: ..."을 조립한다).
        # 비워두면 이름만 보여서 협업 판단 자체가 불가능해진다.
        description="반/기간별 성적을 DB에서 조회하고 집계한다. 데이터에 접근할 수 있는 유일한 에이전트.",
    )


def report_agent(logger_indent: int = 6, owner: str = "") -> Agent:
    return Agent(
        model=MODEL,
        tools=[save_report],
        system_prompt=REPORT_PROMPT,
        hooks=[ToolCallLogger(indent=logger_indent, owner=owner, mark="└ 🔧")],
        callback_handler=None,
        name="report",
        description="전달받은 성적 데이터를 마크다운 표 리포트로 정리해 report.md에 저장한다.",
    )


def message_agent(logger_indent: int = 6, owner: str = "") -> Agent:
    return Agent(
        model=MODEL,
        tools=[save_message],
        system_prompt=MESSAGE_PROMPT,
        hooks=[ToolCallLogger(indent=logger_indent, owner=owner, mark="└ 🔧")],
        callback_handler=None,
        name="message",
        description="전달받은 성적 데이터로 학부모 발송용 문자 초안을 써서 message.md에 저장한다.",
    )


# ── 출력 ────────────────────────────────────────────────────────────────────
PATTERN_TITLE = {
    "tools": "Agents-as-Tools (묶는 사람: 모델)",
    "graph": "Graph 병렬 (묶는 사람: 개발자)",
    "route": "Graph 조건부 라우팅 (묶는 사람: 개발자 + 사람 승인)",
    "swarm": "Swarm 자율 협업 (묶는 사람: 에이전트)",
}


def print_header(pattern: str, question: str) -> None:
    print(f"\n{BAR}")
    print(f" 패턴: {BOLD(PATTERN_TITLE[pattern])}")
    print(f" 질문: {question}")
    print(f" 모델: {DIM(MODEL_ID)}  리전: {DIM(REGION)}")
    print(f"{BAR}\n")


def print_footer(flow: str, elapsed: float, extra: list[str] | None = None) -> None:
    print(f"\n{RULE}")
    print(f" 실행 노드: {flow}")
    print(f" 총 소요:   {BOLD(f'{elapsed:.1f}초')}")
    print(f" 토큰:      입력 {RUN.input_tokens:,} / 출력 {RUN.output_tokens:,}")
    for line in extra or []:
        print(f" {line}")
    print(RULE)


def print_answer(text: str) -> None:
    print(f"\n{BOLD('💬 최종 답변')}\n{str(text).strip()}\n")


# ── 패턴 1: Agents-as-Tools ─────────────────────────────────────────────────
# 전문 에이전트를 @tool로 감싼다. 오케스트레이터는 docstring만 읽고
# "이 질문엔 뭐가 필요한지" 스스로 고른다. 순서를 정하는 건 개발자가 아니라 모델이다.

@tool
def ask_score_query_agent(query: str) -> str:
    """성적 조회 전문 에이전트에게 데이터 조회를 맡깁니다.

    반별/기간별 점수, 평균, 숙제율, 결석 반영 여부가 필요할 때 사용하세요.
    이 에이전트만 실제 데이터베이스에 접근할 수 있습니다.

    Args:
        query: 조회 요청을 한국어 한 문장으로. 반 이름과 기간을 명시하세요.
            예: "3반의 2026년 8월 성적을 조회해줘"

    Returns:
        조회된 성적 데이터 요약(반 평균, 학생별 점수, 숙제율, 결석 현황).
    """
    RUN.note_agent("score_query")
    result = score_query_agent(owner="score_query")(query)
    RUN.add_agent_result(result)
    return str(result)


@tool
def ask_report_agent(data: str) -> str:
    """리포트 작성 전문 에이전트에게 마크다운 리포트 작성을 맡깁니다. report.md로 저장됩니다.

    사용자가 "정리해줘", "리포트", "보고서"를 요청했을 때만 사용하세요.
    단순 조회 질문에는 사용하지 마세요.

    Args:
        data: ask_score_query_agent가 돌려준 성적 데이터를 **그대로** 넣으세요.
            이 에이전트는 데이터를 직접 조회할 수 없습니다.

    Returns:
        저장 결과와 리포트 요약.
    """
    RUN.note_agent("report")
    result = report_agent(owner="report")(data)
    RUN.add_agent_result(result)
    return str(result)


@tool
def ask_message_agent(data: str) -> str:
    """학부모 문자 초안 작성 전문 에이전트에게 문자 초안 작성을 맡깁니다. message.md로 저장됩니다.

    사용자가 "문자", "학부모께 보낼", "안내 메시지"를 요청했을 때만 사용하세요.
    실제로 발송하지는 않습니다. 초안만 만듭니다.

    Args:
        data: ask_score_query_agent가 돌려준 성적 데이터를 **그대로** 넣으세요.

    Returns:
        저장 결과와 문자 초안 본문.
    """
    RUN.note_agent("message")
    result = message_agent(owner="message")(data)
    RUN.add_agent_result(result)
    return str(result)


ORCHESTRATOR_PROMPT = f"""당신은 영어학원 선생님의 요청을 받아 전문 에이전트에게 일을 나눠주는 오케스트레이터입니다.

이 학원 데이터의 시험일 범위는 {DATA_LO} ~ {DATA_HI} 입니다.
"이번 달", "최근" 같은 표현은 **당신이 날짜로 바꾸지 마세요.** 오늘 날짜를 추측하지도 마세요.
그런 표현은 선생님이 쓴 말 그대로 조회 에이전트에게 넘기면, 그쪽이 데이터 기준으로 해석합니다.

부하 에이전트는 셋뿐입니다.
- ask_score_query_agent : 데이터 조회 (이 에이전트만 DB에 접근할 수 있다)
- ask_report_agent      : 마크다운 리포트 작성 → report.md
- ask_message_agent     : 학부모 문자 초안 작성 → message.md

작업 규칙:
1. 데이터가 필요하면 **항상 ask_score_query_agent를 가장 먼저** 부릅니다.
   이때 선생님의 원래 표현("이번 달" 등)을 바꾸지 말고 그대로 담아 넘깁니다.
2. 리포트나 문자를 만들 때는 1번에서 받은 결과 텍스트를 **그대로** 인자로 넘깁니다.
3. **요청받지 않은 일은 절대 하지 마세요.**
   - "평균만 알려줘", "얼마야", "비교해줘" → 조회만 하고 끝냅니다. 리포트도 문자도 만들지 마세요.
   - "정리해줘", "리포트" 라는 말이 있을 때만 ask_report_agent를 부릅니다.
   - "문자", "학부모께" 라는 말이 있을 때만 ask_message_agent를 부릅니다.
4. 당신은 직접 계산하지 않습니다. 숫자는 부하 에이전트가 준 것만 씁니다.

마지막에 한국어로 3~5줄, 선생님이 바로 읽을 수 있게 결과를 정리해 답하세요.
만든 파일이 있으면 파일명을 언급하세요.
"""


def run_tools(question: str) -> None:
    orchestrator = Agent(
        model=MODEL,
        tools=[ask_score_query_agent, ask_report_agent, ask_message_agent],
        system_prompt=ORCHESTRATOR_PROMPT,
        hooks=[ToolCallLogger(indent=3, mark="🔧")],
        callback_handler=None,
        name="orchestrator",
    )
    print(f"{CYAN('🤖')} {BOLD('orchestrator')}")

    started = time.time()
    result = orchestrator(question)
    elapsed = time.time() - started
    RUN.add_agent_result(result)

    print_answer(result)
    called = RUN.agents_called or ["(없음)"]
    print_footer(
        flow=" → ".join(called),
        elapsed=elapsed,
        extra=[f"호출된 전문 에이전트: {len(RUN.agents_called)}개 · 순서 결정: 모델"],
    )


# ── 패턴 2: Graph 병렬 ───────────────────────────────────────────────────────
# 순서를 모델이 고르지 않는다. 내가 엣지로 그린다.
#
#         score_query
#         ╱          ╲
#    report          message      ← 여기가 병렬
#         ╲          ╱
#          summary

SUMMARY_PROMPT = """당신은 앞 단계 결과 두 개를 받아 선생님께 한 번에 보고하는 정리 에이전트입니다.

리포트 담당과 문자 담당이 각각 만든 결과를 전달받습니다.
**새로 조회하거나 계산하지 마세요.** 전달받은 내용만 씁니다.

한국어로 5줄 이내로 정리하세요.
1. 반 평균과 숙제율 핵심 숫자 한 줄
2. 리포트에서 눈에 띄는 점 한두 줄
3. 문자 초안이 어떤 톤으로 나왔는지 한 줄
4. 만들어진 파일(report.md, message.md)을 마지막 줄에 언급
"""


def _summary_agent() -> Agent:
    return Agent(
        model=MODEL,
        system_prompt=SUMMARY_PROMPT,
        callback_handler=None,
        name="summary",
        description="앞 에이전트들의 결과를 합쳐 선생님께 보고할 최종 요약을 쓴다. 마지막 단계.",
    )


def flow_from_spans() -> str:
    """실제 실행 시간대를 보고 '뭐가 뭐랑 동시에 돌았는지'를 그려낸다.

    겹친 구간은 ∥ 로 묶는다. 이건 그림이 아니라 실측이다.
    """
    spans = sorted(RUN.spans, key=lambda x: x[1])
    groups: list[list[tuple[str, float, float]]] = []
    for span in spans:
        placed = False
        for group in groups:
            if any(min(span[2], g[2]) - max(span[1], g[1]) > 0 for g in group):
                group.append(span)
                placed = True
                break
        if not placed:
            groups.append([span])
    return " → ".join(" ∥ ".join(n for n, _, _ in g) for g in groups)


def build_graph():
    builder = GraphBuilder()
    builder.add_node(score_query_agent(owner="score_query"), "score_query")
    builder.add_node(report_agent(owner="report"), "report")
    builder.add_node(message_agent(owner="message"), "message")
    builder.add_node(_summary_agent(), "summary")

    builder.set_entry_point("score_query")
    builder.add_edge("score_query", "report")
    builder.add_edge("score_query", "message")
    builder.add_edge("report", "summary")
    builder.add_edge("message", "summary")

    # 발표장에서 무한 대기하지 않도록 한도를 못 박는다. (기본값은 무제한)
    builder.set_max_node_executions(8)
    builder.set_execution_timeout(300.0)
    builder.set_node_timeout(120.0)

    builder.set_hook_providers([NodeCallLogger()])
    return builder.build()


def run_graph(question: str) -> None:
    graph = build_graph()
    print(DIM("엣지: score_query → report / score_query → message / report,message → summary"))

    started = time.time()
    result = graph(question)
    elapsed = time.time() - started
    RUN.add_usage(result.accumulated_usage)

    print_answer(result.results["summary"] if "summary" in result.results else result)

    # ── 검증 4: 병렬이 실제로 이득이었나 ──────────────────────────────────
    per_node = {nid: nr.execution_time / 1000 for nid, nr in result.results.items()}
    node_sum = sum(per_node.values())
    detail = "  ".join(f"{k} {v:.1f}s" for k, v in per_node.items())
    overlaps = RUN.parallel_pairs()
    overlap_lines = [f"병렬 실측: {a} ∥ {b} 가 {sec:.1f}초 겹침" for a, b, sec in overlaps] or \
                    ["병렬 실측: 겹친 구간 없음 (순차로 돌았다)"]
    verdict = "✅ 병렬 이득 있음" if elapsed < node_sum else "❌ 병렬 이득 없음"

    print_footer(
        flow=flow_from_spans(),
        elapsed=elapsed,
        extra=[
            f"노드별 소요: {detail}",
            f"순차로 돌렸다면: {node_sum:.1f}초  ·  실제 그래프: {elapsed:.1f}초  →  {verdict}",
            *overlap_lines,
            "호출된 전문 에이전트: 4개 · 순서 결정: 개발자(엣지)",
        ],
    )


# ── 패턴 3: Graph 조건부 라우팅 + 사람 승인 ─────────────────────────────────
# 조회는 되돌릴 수 있다. 학부모에게 나간 문자는 되돌릴 수 없다.
# 그래서 발송 경로에만 사람 확인을 끼운다. 이 비대칭이 이 패턴의 전부다.
#
#   classifier ─(QUERY)→ score_query        바로 실행
#              └(SEND)──→ message           사람이 y 를 눌러야 실행

CLASSIFIER_PROMPT = """당신은 학원 선생님의 요청을 두 갈래로 분류하는 라우터입니다.

- QUERY : 성적/평균/점수/숙제율을 **알아보려는** 요청. 조회, 비교, 확인, 정리.
- SEND  : 학부모나 학생에게 **문자/메시지를 보내려는** 요청. 발송, 안내, 전송, 문자.

판단이 애매하면 QUERY 로 분류하세요. 보내는 쪽은 되돌릴 수 없으니 더 신중해야 합니다.

출력 형식(엄수): 설명하지 말고 **QUERY 또는 SEND 한 단어만** 출력하세요.
"""


def _classifier_agent() -> Agent:
    return Agent(
        model=MODEL,
        system_prompt=CLASSIFIER_PROMPT,
        callback_handler=None,
        name="classifier",
    )


def _label(state) -> str:
    """classifier 노드가 뭐라고 분류했는지 읽는다."""
    node_result = state.results.get("classifier")
    if node_result is None:
        return ""
    text = str(node_result).upper()
    if "SEND" in text:
        return "SEND"
    if "QUERY" in text:
        return "QUERY"
    return ""


def is_query(state) -> bool:
    """조회 경로 엣지 조건. 되돌릴 수 있는 작업이라 확인 없이 통과시킨다."""
    return _label(state) == "QUERY"


class ApprovalGate:
    """발송 경로 엣지 조건. 사람이 y 를 눌러야만 True 를 돌려준다.

    주의: Strands 1.54.0은 엣지 조건을 노드당 최대 두 번 평가한다
    (_is_node_ready_with_conditions 에서 한 번, _build_node_input 에서 또 한 번).
    그래서 물어본 답을 반드시 캐시해야 승인 프롬프트가 두 번 뜨지 않는다.
    """

    def __init__(self):
        self.decision: bool | None = None

    def __call__(self, state) -> bool:
        if _label(state) != "SEND":
            return False
        if self.decision is None:
            self.decision = self._ask()
        return self.decision

    @staticmethod
    def _ask() -> bool:
        print()
        print(YELLOW("⚠️  발송 경로로 분기되었습니다."))
        print("    대상: 3반 학부모")
        print("    이 실습에서는 실제 발송하지 않고 초안만 만듭니다.")
        try:
            answer = input("    계속할까요? (y/n) ").strip().lower()
        except EOFError:
            answer = "n"
        ok = answer in ("y", "yes", "ㅇ")
        print(GREEN("    ✅ 승인됨 — message 노드를 실행합니다.") if ok
              else DIM("    ⛔ 거부됨 — 아무것도 만들지 않고 종료합니다."))
        return ok


def run_route(question: str) -> None:
    gate = ApprovalGate()

    builder = GraphBuilder()
    builder.add_node(_classifier_agent(), "classifier")
    builder.add_node(score_query_agent(owner="score_query"), "score_query")
    builder.add_node(message_agent(owner="message"), "message")

    builder.set_entry_point("classifier")
    builder.add_edge("classifier", "score_query", condition=is_query)
    builder.add_edge("classifier", "message", condition=gate)

    builder.set_max_node_executions(6)
    builder.set_execution_timeout(300.0)
    builder.set_node_timeout(120.0)
    builder.set_hook_providers([NodeCallLogger()])
    graph = builder.build()

    print(DIM("엣지: classifier ─(QUERY)→ score_query / classifier ─(SEND, 사람 승인)→ message"))

    started = time.time()
    result = graph(question)
    elapsed = time.time() - started
    RUN.add_usage(result.accumulated_usage)

    order = [node.node_id for node in result.execution_order]
    label = _label(graph.state) or "(분류 실패)"
    last = order[-1] if order else None
    if gate.decision is False:
        print_answer("발송이 취소되었습니다. message.md는 만들지 않았습니다.")
    else:
        print_answer(result.results[last] if last else "실행된 노드가 없습니다.")

    if label == "SEND" and gate.decision is False:
        taken = "SEND 로 분류 → 사람이 거부 → 중단"
    elif label == "SEND":
        taken = "SEND 로 분류 → 사람이 승인 → message 실행"
    else:
        taken = "QUERY 로 분류 → 확인 없이 score_query 실행"

    print_footer(
        flow=" → ".join(order) or "(classifier 만 실행)",
        elapsed=elapsed,
        extra=[
            f"분류 결과: {BOLD(label)}",
            f"선택된 경로: {taken}",
            f"호출된 전문 에이전트: {len(order)}개 · 순서 결정: 개발자(조건부 엣지)",
        ],
    )


# ── 패턴 4: Swarm — 비교용 (왜 안 쓰는지 보여주기) ───────────────────────────
# 이 패턴은 "좋다"를 보여주려고 있는 게 아니다.
# 넘길지 말지를 에이전트끼리 정하게 하면, 학원 업무처럼 순서가 뻔한 일에는
# handoff 왕복만 늘어난다는 걸 **실행 결과로** 보여주려고 있다.
#
# 타임아웃을 짧게 못 박는다. 워크샵 기본값(900초)을 그대로 두면 발표가 멈춘다.

SWARM_TIMEOUT = 90.0
SWARM_NODE_TIMEOUT = 30.0


def run_swarm(question: str) -> None:
    # Swarm은 넘겨받은 Agent 객체에 handoff 도구를 주입한다(= 객체를 건드린다).
    # 그래서 다른 패턴과 공유하지 않고 여기서 새로 만든다.
    nodes = [
        score_query_agent(owner="score_query"),
        report_agent(owner="report"),
        message_agent(owner="message"),
        _summary_agent(),
    ]
    swarm = Swarm(
        nodes,
        entry_point=nodes[0],
        max_handoffs=6,
        max_iterations=6,
        execution_timeout=SWARM_TIMEOUT,
        node_timeout=SWARM_NODE_TIMEOUT,
        hooks=[NodeCallLogger()],
    )
    print(DIM(f"자율 협업: 4개 에이전트가 handoff_to_agent 도구로 서로 넘긴다 "
              f"(max_handoffs=6, 전체 {SWARM_TIMEOUT:.0f}s / 노드 {SWARM_NODE_TIMEOUT:.0f}s 제한)"))

    started = time.time()
    outcome = "정상 종료"
    answer = None
    try:
        result = swarm(question)
        answer = result
        outcome = f"정상 종료 (status={result.status.value})"
    except Exception as exc:
        # 타임아웃도 여기로 온다. 죽지 않고 여기까지 온 기록을 그대로 보여준다.
        # 멈췄다는 사실 자체가 이 패턴에 대한 논거다.
        outcome = f"중단됨 — {type(exc).__name__}: {_preview(exc, 60)}"
    elapsed = time.time() - started

    state = swarm.state
    RUN.add_usage(state.accumulated_usage)

    history = [node.node_id for node in state.node_history]
    handoffs = max(len(history) - 1, 0)

    if answer is not None:
        print_answer(answer)
    else:
        done = [nid for nid, nr in state.results.items() if nr.status.value == "completed"]
        print_answer(f"완주하지 못했습니다. 여기까지 끝낸 노드: {', '.join(done) or '없음'}")

    print_footer(
        flow=" → ".join(history) or "(실행 없음)",
        elapsed=elapsed,
        extra=[
            f"결과: {BOLD(outcome)}",
            f"handoff 이력: {' → '.join(history) or '없음'}  (handoff {handoffs}회)",
            f"호출된 전문 에이전트: {len(set(history))}개 · 순서 결정: 에이전트 자신",
        ],
    )


# ── main ────────────────────────────────────────────────────────────────────
DEFAULT_QUESTION = {
    "tools": "3반 이번 달 성적 정리하고, 학부모님께 보낼 문자 초안까지 만들어줘",
    "graph": "3반 이번 달 성적 정리하고, 학부모님께 보낼 문자 초안까지 만들어줘",
    "route": "3반 평균 알려줘",
    "swarm": "3반 이번 달 성적 정리하고, 학부모님께 보낼 문자 초안까지 만들어줘",
}

RUNNERS = {
    "tools": run_tools,
    "graph": run_graph,
    "route": run_route,
    "swarm": run_swarm,
}


def main() -> None:
    global T0
    parser = argparse.ArgumentParser(description="Strands 멀티에이전트 패턴 4종 비교")
    parser.add_argument("--pattern", required=True, choices=["tools", "graph", "route", "swarm"])
    parser.add_argument("-q", "--query", default=None, help="사용자 질문 (생략 시 패턴별 기본 질문)")
    args = parser.parse_args()

    question = args.query or DEFAULT_QUESTION[args.pattern]
    print_header(args.pattern, question)
    T0 = time.time()
    RUNNERS[args.pattern](question)


if __name__ == "__main__":
    main()
