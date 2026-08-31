"""AgentCore Runtime에 올리는 엔트리포인트.

로컬 agent.py와 **에이전트 정의는 똑같다.** 같은 도구 3개, 같은 시스템 프롬프트.
달라지는 건 딱 두 가지다.

    로컬:  터미널이 질문을 받고 → print로 답한다
    배포:  HTTP 요청이 질문을 받고 → JSON으로 답한다

그래서 이 파일은 "감싸는 껍데기"일 뿐이다. tools.py는 한 줄도 안 바뀐 채로
그대로 올라간다. 발표에서 말하려는 게 바로 이거다.
"""

from collections import OrderedDict

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.hooks import AfterToolCallEvent, BeforeToolCallEvent, HookProvider, HookRegistry
from strands.models import BedrockModel

import db
from tools import aggregate, list_classes, query_scores

app = BedrockAgentCoreApp()
log = app.logger

# 로컬 agent.py와 동일한 값을 쓴다 (서울에서 실호출로 확인한 프로파일)
MODEL_ID = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
REGION = "ap-northeast-2"


class ToolTrace(HookProvider):
    """어떤 도구가 어떤 인자로 불렸는지 모은다.

    로컬에서는 터미널에 찍었지만, 배포판에서는 응답 JSON에 실어 보낸다.
    CloudWatch 로그에도 같이 남긴다.
    """

    def __init__(self):
        self.calls: list[dict] = []

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self.before_tool)
        registry.add_callback(AfterToolCallEvent, self.after_tool)

    def before_tool(self, event: BeforeToolCallEvent) -> None:
        entry = {"tool": event.tool_use["name"], "input": event.tool_use.get("input") or {}}
        self.calls.append(entry)
        # rows를 통째로 찍으면 CloudWatch 로그가 폭발한다. 요약해서 남긴다.
        log.info("tool_call %s", _fmt_call(entry))

    def after_tool(self, event: AfterToolCallEvent) -> None:
        log.info(
            "tool_done name=%s status=%s duration=%s",
            event.tool_use["name"],
            event.result.get("status"),
            event.duration,
        )


def _fmt_call(call: dict) -> str:
    """툴 호출 한 건을 사람이 읽는 한 줄로. rows처럼 긴 배열은 개수로 줄인다."""
    parts = []
    for key, value in (call["input"] or {}).items():
        if isinstance(value, list) and len(value) > 6:
            parts.append(f"{key}=[{len(value)}개 항목]")
        else:
            parts.append(f"{key}={value!r}")
    return f"{call['tool']}({', '.join(parts)})"


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


SYSTEM_PROMPT = build_system_prompt()


def _agent_factory():
    """세션별로 Agent를 재사용한다. "결석 빼고 다시 내줘" 같은 후속 질문이
    앞 대화를 이어받게 하려면 히스토리가 살아 있어야 한다."""
    cache: OrderedDict[str, tuple[Agent, ToolTrace]] = OrderedDict()

    def get_or_create(session_id: str):
        if session_id in cache:
            cache.move_to_end(session_id)
            return cache[session_id]
        if len(cache) >= 128:
            cache.popitem(last=False)
        trace = ToolTrace()
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID, region_name=REGION, temperature=0, streaming=False),
            tools=[list_classes, query_scores, aggregate],
            system_prompt=SYSTEM_PROMPT,
            hooks=[trace],
            callback_handler=None,
        )
        cache[session_id] = (agent, trace)
        return cache[session_id]

    return get_or_create


get_or_create_agent = _agent_factory()


@app.entrypoint
def invoke(payload, context):
    """{"prompt": "중2 반들 중에 숙제율 제일 낮은 반이 어디야?"} 를 받는다."""
    if not isinstance(payload, dict):
        return {"error": "payload는 JSON 객체여야 합니다."}
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": 'prompt 문자열이 필요합니다. 예: {"prompt": "3반 평균 알려줘"}'}

    session_id = getattr(context, "session_id", None) or "default-session"
    agent, trace = get_or_create_agent(session_id)
    trace.calls = []

    log.info("invoke session=%s prompt=%s", session_id, prompt)
    result = agent(prompt)
    answer = "".join(block.get("text", "") for block in result.message.get("content", [])).strip()

    return {
        "answer": answer,
        # 어떤 도구를 어떤 인자로 골랐는지 — 발표에서 보여줄 부분
        "tools_used": [_fmt_call(c) for c in trace.calls],
        "model": MODEL_ID,
        "region": REGION,
    }


if __name__ == "__main__":
    app.run()
