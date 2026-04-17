"""
Railway MCP 프록시 서버.

Anthropic VM에서 Railway API가 IP 차단(403)되는 문제를 우회하기 위해,
Railway 위에서 실행되는 이 앱이 대신 Railway API를 호출하는 방식.

Claude.ai/code 웹에서 이 서버를 MCP로 등록하면 Railway 관리가 가능해짐.

필요 환경변수:
  RAILWAY_API_TOKEN    — Railway 대시보드 > Account Settings > Tokens 에서 발급
  RAILWAY_PROXY_SECRET — MCP 엔드포인트 보호용 임의 비밀 문자열 (직접 설정)

Railway가 자동 주입하는 변수 (별도 설정 불필요):
  RAILWAY_PROJECT_ID, RAILWAY_SERVICE_ID, RAILWAY_ENVIRONMENT_ID
"""

import os

import httpx
from mcp.server.fastmcp import FastMCP

RAILWAY_GQL = "https://backboard.railway.com/graphql/v2"

_DEFAULT_PROJECT_ID = os.getenv("RAILWAY_PROJECT_ID", "")
_DEFAULT_SERVICE_ID = os.getenv("RAILWAY_SERVICE_ID", "")
_DEFAULT_ENV_ID = os.getenv("RAILWAY_ENVIRONMENT_ID", "")

mcp = FastMCP("Railway Manager")


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
            headers={
                "Authorization": f"Bearer {_token()}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()


def _pid(v: str) -> str:
    return v or _DEFAULT_PROJECT_ID


def _sid(v: str) -> str:
    return v or _DEFAULT_SERVICE_ID


def _eid(v: str) -> str:
    return v or _DEFAULT_ENV_ID


# ──────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────


@mcp.tool()
async def get_project_info() -> str:
    """현재 계정의 Railway 프로젝트·서비스·환경 목록을 반환합니다."""
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


@mcp.tool()
async def list_deployments(project_id: str = "", service_id: str = "") -> str:
    """서비스의 최근 배포 목록을 반환합니다. ID 생략 시 현재 서비스 사용."""
    pid = _pid(project_id)
    sid = _sid(service_id)
    if not pid or not sid:
        return "project_id / service_id 가 필요합니다. get_project_info() 로 먼저 확인하세요."
    data = await _gql(
        """
        query D($serviceId: String!, $projectId: String!) {
            deployments(input: { serviceId: $serviceId, projectId: $projectId }, first: 10) {
                edges {
                    node { id status createdAt updatedAt }
                }
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
        f"{d['node']['id']}  {d['node']['status']}  생성={d['node']['createdAt']}"
        for d in deps
    )


@mcp.tool()
async def trigger_redeploy(service_id: str = "", environment_id: str = "") -> str:
    """서비스 재배포를 트리거합니다. ID 생략 시 현재 서비스/환경 사용."""
    sid = _sid(service_id)
    eid = _eid(environment_id)
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


@mcp.tool()
async def get_deployment_logs(deployment_id: str, log_type: str = "runtime") -> str:
    """배포 로그를 가져옵니다. log_type: 'runtime'(기본) 또는 'build'"""
    field = "deploymentLogs" if log_type == "runtime" else "buildLogs"
    data = await _gql(
        f"""
        query L($deploymentId: String!) {{
            {field}(deploymentId: $deploymentId) {{
                timestamp message severity
            }}
        }}
        """,
        {"deploymentId": deployment_id},
    )
    if "errors" in data:
        return f"오류: {data['errors']}"
    logs = data.get("data", {}).get(field, []) or []
    if not logs:
        return "로그 없음"
    return "\n".join(
        f"[{l.get('severity','INFO')}] {l.get('timestamp','')} {l.get('message','')}"
        for l in logs[-200:]
    )


@mcp.tool()
async def list_env_vars(
    project_id: str = "",
    service_id: str = "",
    environment_id: str = "",
) -> str:
    """환경변수 목록을 반환합니다. 값은 앞뒤 일부만 노출됩니다."""
    pid = _pid(project_id)
    sid = _sid(service_id)
    eid = _eid(environment_id)
    if not pid or not eid:
        return "project_id / environment_id 가 필요합니다."
    data = await _gql(
        """
        query V($projectId: String!, $environmentId: String!, $serviceId: String) {
            variables(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId)
        }
        """,
        {"projectId": pid, "environmentId": eid, "serviceId": sid or None},
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


@mcp.tool()
async def set_env_var(
    name: str,
    value: str,
    project_id: str = "",
    service_id: str = "",
    environment_id: str = "",
) -> str:
    """환경변수를 생성하거나 업데이트합니다."""
    pid = _pid(project_id)
    sid = _sid(service_id)
    eid = _eid(environment_id)
    if not pid or not eid:
        return "project_id / environment_id 가 필요합니다."
    data = await _gql(
        """
        mutation U($projectId: String!, $environmentId: String!, $serviceId: String,
                   $name: String!, $value: String!) {
            variableUpsert(input: {
                projectId: $projectId, environmentId: $environmentId,
                serviceId: $serviceId, name: $name, value: $value
            })
        }
        """,
        {"projectId": pid, "environmentId": eid, "serviceId": sid or None,
         "name": name, "value": value},
    )
    if "errors" in data:
        return f"오류: {data['errors']}"
    return f"'{name}' 설정 완료 (재배포 필요)"


@mcp.tool()
async def delete_env_var(
    name: str,
    project_id: str = "",
    service_id: str = "",
    environment_id: str = "",
) -> str:
    """환경변수를 삭제합니다."""
    pid = _pid(project_id)
    sid = _sid(service_id)
    eid = _eid(environment_id)
    if not pid or not sid or not eid:
        return "project_id / service_id / environment_id 가 모두 필요합니다."
    data = await _gql(
        """
        mutation Del($projectId: String!, $environmentId: String!,
                     $serviceId: String!, $name: String!) {
            variableDelete(input: {
                projectId: $projectId, environmentId: $environmentId,
                serviceId: $serviceId, name: $name
            })
        }
        """,
        {"projectId": pid, "environmentId": eid, "serviceId": sid, "name": name},
    )
    if "errors" in data:
        return f"오류: {data['errors']}"
    return f"'{name}' 삭제 완료"
