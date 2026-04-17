"""
Railway MCP 프록시 — mcp 패키지 없이 MCP HTTP 프로토콜 직접 구현.
"""

import os
import httpx

RAILWAY_GQL = "https://backboard.railway.com/graphql/v2"

_DEFAULT_PROJECT_ID = os.getenv("RAILWAY_PROJECT_ID", "")
_DEFAULT_SERVICE_ID = os.getenv("RAILWAY_SERVICE_ID", "")
_DEFAULT_ENV_ID = os.getenv("RAILWAY_ENVIRONMENT_ID", "")


def _token() -> str:
    t = os.getenv("RAILWAY_API_TOKEN", "").strip()
    if not t:
        raise ValueError("RAILWAY_API_TOKEN 환경변수가 설정되지 않았습니다.")
    return t


async def _gql(query: str, variables: dict | None = None) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            RAILWAY_GQL,
            json={"query": query, "variables": variables or {}},
            headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()


def _p(v, d): return v or d


# ── MCP Tool 정의 ────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_project_info",
        "description": "Railway 프로젝트·서비스·환경 목록을 반환합니다.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_deployments",
        "description": "서비스의 최근 배포 목록을 반환합니다. ID 생략 시 현재 서비스 사용.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "프로젝트 ID (생략 가능)"},
                "service_id": {"type": "string", "description": "서비스 ID (생략 가능)"},
            },
        },
    },
    {
        "name": "trigger_redeploy",
        "description": "서비스 재배포를 트리거합니다. ID 생략 시 현재 서비스/환경 사용.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service_id": {"type": "string"},
                "environment_id": {"type": "string"},
            },
        },
    },
    {
        "name": "get_deployment_logs",
        "description": "배포 로그를 가져옵니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "deployment_id": {"type": "string"},
                "log_type": {"type": "string", "enum": ["runtime", "build"], "default": "runtime"},
            },
            "required": ["deployment_id"],
        },
    },
    {
        "name": "list_env_vars",
        "description": "환경변수 목록을 반환합니다 (값 마스킹).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "service_id": {"type": "string"},
                "environment_id": {"type": "string"},
            },
        },
    },
    {
        "name": "set_env_var",
        "description": "환경변수를 생성하거나 업데이트합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "value": {"type": "string"},
                "project_id": {"type": "string"},
                "service_id": {"type": "string"},
                "environment_id": {"type": "string"},
            },
            "required": ["name", "value"],
        },
    },
    {
        "name": "delete_env_var",
        "description": "환경변수를 삭제합니다.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "project_id": {"type": "string"},
                "service_id": {"type": "string"},
                "environment_id": {"type": "string"},
            },
            "required": ["name"],
        },
    },
]


# ── Tool 핸들러 ─────────────────────────────────────────────────

async def _get_project_info(_args: dict) -> str:
    data = await _gql("""
        query {
            me {
                projects {
                    edges {
                        node {
                            id name
                            environments { edges { node { id name } } }
                            services { edges { node { id name } } }
                        }
                    }
                }
            }
        }
    """)
    if "errors" in data:
        return f"오류: {data['errors']}"
    projects = data.get("data", {}).get("me", {}).get("projects", {}).get("edges", [])
    lines: list[str] = []
    for p in projects:
        n = p["node"]
        lines.append(f"[프로젝트] {n['name']}  id={n['id']}")
        for e in n.get("environments", {}).get("edges", []):
            lines.append(f"  환경: {e['node']['name']}  id={e['node']['id']}")
        for s in n.get("services", {}).get("edges", []):
            lines.append(f"  서비스: {s['node']['name']}  id={s['node']['id']}")
    return "\n".join(lines) if lines else "프로젝트 없음"


async def _list_deployments(args: dict) -> str:
    pid = _p(args.get("project_id", ""), _DEFAULT_PROJECT_ID)
    sid = _p(args.get("service_id", ""), _DEFAULT_SERVICE_ID)
    if not pid or not sid:
        return "project_id / service_id 가 필요합니다. get_project_info 로 먼저 확인하세요."
    data = await _gql(
        """
        query D($serviceId: String!, $projectId: String!) {
            deployments(input: { serviceId: $serviceId, projectId: $projectId }, first: 10) {
                edges { node { id status createdAt updatedAt } }
            }
        }
        """,
        {"serviceId": sid, "projectId": pid},
    )
    if "errors" in data:
        return f"오류: {data['errors']}"
    deps = data.get("data", {}).get("deployments", {}).get("edges", [])
    if not deps:
        return "배포 없음"
    return "\n".join(
        f"{d['node']['id']}  {d['node']['status']}  {d['node']['createdAt']}" for d in deps
    )


async def _trigger_redeploy(args: dict) -> str:
    sid = _p(args.get("service_id", ""), _DEFAULT_SERVICE_ID)
    eid = _p(args.get("environment_id", ""), _DEFAULT_ENV_ID)
    if not sid or not eid:
        return "service_id / environment_id 가 필요합니다."
    data = await _gql(
        """
        mutation R($serviceId: String!, $environmentId: String!) {
            serviceInstanceRedeploy(serviceId: $serviceId, environmentId: $environmentId)
        }
        """,
        {"serviceId": sid, "environmentId": eid},
    )
    if "errors" in data:
        return f"오류: {data['errors']}"
    return "재배포 트리거 성공"


async def _get_deployment_logs(args: dict) -> str:
    dep_id = args.get("deployment_id", "")
    if not dep_id:
        return "deployment_id 가 필요합니다."
    field = "deploymentLogs" if args.get("log_type", "runtime") == "runtime" else "buildLogs"
    data = await _gql(
        f"query L($d: String!) {{ {field}(deploymentId: $d) {{ timestamp message severity }} }}",
        {"d": dep_id},
    )
    if "errors" in data:
        return f"오류: {data['errors']}"
    logs = data.get("data", {}).get(field) or []
    if not logs:
        return "로그 없음"
    return "\n".join(
        f"[{l.get('severity','INFO')}] {l.get('timestamp','')} {l.get('message','')}"
        for l in logs[-200:]
    )


async def _list_env_vars(args: dict) -> str:
    pid = _p(args.get("project_id", ""), _DEFAULT_PROJECT_ID)
    sid = _p(args.get("service_id", ""), _DEFAULT_SERVICE_ID)
    eid = _p(args.get("environment_id", ""), _DEFAULT_ENV_ID)
    if not pid or not eid:
        return "project_id / environment_id 가 필요합니다."
    data = await _gql(
        "query V($p: String!, $e: String!, $s: String) { variables(projectId: $p, environmentId: $e, serviceId: $s) }",
        {"p": pid, "e": eid, "s": sid or None},
    )
    if "errors" in data:
        return f"오류: {data['errors']}"
    variables: dict = data.get("data", {}).get("variables") or {}
    if not variables:
        return "환경변수 없음"
    lines: list[str] = []
    for k, v in sorted(variables.items()):
        masked = (v[:4] + "..." + v[-4:]) if len(v) > 10 else "***"
        lines.append(f"{k} = {masked}")
    return "\n".join(lines)


async def _set_env_var(args: dict) -> str:
    name = args.get("name", "")
    value = args.get("value", "")
    pid = _p(args.get("project_id", ""), _DEFAULT_PROJECT_ID)
    sid = _p(args.get("service_id", ""), _DEFAULT_SERVICE_ID)
    eid = _p(args.get("environment_id", ""), _DEFAULT_ENV_ID)
    if not name or not pid or not eid:
        return "name / project_id / environment_id 가 필요합니다."
    data = await _gql(
        """
        mutation U($p: String!, $e: String!, $s: String, $n: String!, $v: String!) {
            variableUpsert(input: { projectId: $p, environmentId: $e, serviceId: $s, name: $n, value: $v })
        }
        """,
        {"p": pid, "e": eid, "s": sid or None, "n": name, "v": value},
    )
    if "errors" in data:
        return f"오류: {data['errors']}"
    return f"'{name}' 설정 완료 (재배포 필요)"


async def _delete_env_var(args: dict) -> str:
    name = args.get("name", "")
    pid = _p(args.get("project_id", ""), _DEFAULT_PROJECT_ID)
    sid = _p(args.get("service_id", ""), _DEFAULT_SERVICE_ID)
    eid = _p(args.get("environment_id", ""), _DEFAULT_ENV_ID)
    if not name or not pid or not sid or not eid:
        return "name / project_id / service_id / environment_id 가 모두 필요합니다."
    data = await _gql(
        """
        mutation Del($p: String!, $e: String!, $s: String!, $n: String!) {
            variableDelete(input: { projectId: $p, environmentId: $e, serviceId: $s, name: $n })
        }
        """,
        {"p": pid, "e": eid, "s": sid, "n": name},
    )
    if "errors" in data:
        return f"오류: {data['errors']}"
    return f"'{name}' 삭제 완료"


_HANDLERS = {
    "get_project_info": _get_project_info,
    "list_deployments": _list_deployments,
    "trigger_redeploy": _trigger_redeploy,
    "get_deployment_logs": _get_deployment_logs,
    "list_env_vars": _list_env_vars,
    "set_env_var": _set_env_var,
    "delete_env_var": _delete_env_var,
}


async def call_tool(name: str, arguments: dict) -> str:
    handler = _HANDLERS.get(name)
    if not handler:
        return f"알 수 없는 도구: {name}"
    try:
        return await handler(arguments)
    except Exception as exc:
        return f"오류: {exc}"
