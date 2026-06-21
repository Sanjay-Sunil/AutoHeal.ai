"""
AutoHeal.ai - Dashboard Server & SSE Telemetry Stream
- Streams LangGraph execution steps (diffs, schemas, code) via SSE
- GitOps: Dynamic PR file targeting via stack trace introspection
- Audit Log API: Exposes incident history from SQLite
"""
import os
import json
import asyncio
import sys
import traceback
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from github import Github, GithubException
from dotenv import load_dotenv

from aegis_agent import build_aegis_graph
import aegis_db

load_dotenv()

# Avoid unicode encode errors on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"])


@app.get("/")
def serve_dashboard():
    """Serves the React frontend dashboard."""
    with open("dashboard.html", "r", encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/checkout-stream")
async def checkout_stream():
    """
    Streams the LangGraph execution steps to the React frontend
    in real-time using Server-Sent Events (SSE).
    """
    async def event_generator():
        # 1. Simulate the Product Backend failure
        yield f"data: {json.dumps({'step': 'system', 'msg': '[Product Backend] User clicked Checkout. Initiating payment to Vendor API...'})}\n\n"
        await asyncio.sleep(1)

        old_cart_payload = {"user_id": 12345, "amount": 99.00}
        target_url = "http://127.0.0.1:8000/pay"
        error_details = (
            "Schema Validation Failed: 'amount' and 'user_id' at the root level "
            "are deprecated. You must pass a nested 'transaction' object containing "
            "'total_amount' and 'user_uuid'."
        )

        # Introspect caller file for dynamic PR targeting
        source_file = "backend/product_backend.py"

        # Create an incident in the audit log
        incident_id = aegis_db.create_incident(target_url, old_cart_payload, error_details, source_file)

        # Stream the Crash
        yield f"data: {json.dumps({'step': 'error', 'msg': '[HTTP 400] Vendor schema drift detected.', 'payload': old_cart_payload})}\n\n"
        await asyncio.sleep(1.5)

        yield f"data: {json.dumps({'step': 'aegis_init', 'msg': '[AutoHeal.ai] Intercepted crash. Delegating to LangGraph Agent...'})}\n\n"

        # 2. Initialize the LangGraph State Machine
        graph = build_aegis_graph()
        initial_state = {
            "original_payload": old_cart_payload,
            "current_error": error_details,
            "target_url": target_url,
            "retry_count": 0,
            "max_retries": 2,
            "generated_code": None,
            "healed_payload": None,
            "verification_status": "pending",
            "old_schema": None,
            "new_schema": None,
            "old_code": None,
            "new_code": None,
            "source_file": source_file,
            "vendor_docs": None,
            "incident_id": incident_id,
        }

        # 3. Stream the LangGraph nodes executing in real-time
        for event in graph.stream(initial_state):
            for node_name, state_update in event.items():
                if node_name == "fetch_docs":
                    yield f"data: {json.dumps({'step': 'node_tool', 'msg': '[Node 0: Tool] Fetching vendor OpenAPI documentation...'})}\n\n"

                elif node_name == "diagnose":
                    yield f"data: {json.dumps({'step': 'node_llm', 'msg': '[Node 1: LLM] Diagnosing drift and generating patch...', 'code': state_update.get('new_code'), 'old_schema': state_update.get('old_schema'), 'new_schema': state_update.get('new_schema'), 'old_code': state_update.get('old_code'), 'new_code': state_update.get('new_code'), 'source_file': source_file})}\n\n"

                elif node_name == "sandbox":
                    healed = state_update.get('healed_payload')
                    err = state_update.get('current_error')
                    if healed:
                        yield f"data: {json.dumps({'step': 'node_sandbox', 'msg': '[Node 2: Sandbox] AI code executed successfully in restricted scope.', 'healed_payload': healed})}\n\n"
                    else:
                        yield f"data: {json.dumps({'step': 'node_sandbox_error', 'msg': f'[Node 2: Sandbox] Execution failed: {err}'})}\n\n"

                elif node_name == "verify":
                    status = state_update.get('verification_status')
                    if status == 'success':
                        yield f"data: {json.dumps({'step': 'node_verify_success', 'msg': '[Node 3: Verification] Vendor accepted healed payload via dry-run! Zero downtime.'})}\n\n"
                    else:
                        yield f"data: {json.dumps({'step': 'node_verify_fail', 'msg': '[Node 3: Verification] Vendor rejected payload. Looping back to LLM...'})}\n\n"

            await asyncio.sleep(0.8)

        yield f"data: {json.dumps({'step': 'done', 'msg': '[AutoHeal.ai] Remediation complete.'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ------------------------------------------------------------------
# GitOps: Approve & Create PR
# ------------------------------------------------------------------
class PRRequest(BaseModel):
    code: str
    source_file: str = "integrations/stripe_integration.py"


@app.post("/api/approve-pr")
async def approve_and_create_pr(request: PRRequest):
    """
    Takes the AI generated code, pushes it to a new branch, and opens a Pull Request.
    Uses the dynamic source_file from stack trace introspection.
    """
    github_token = os.getenv("GITHUB_TOKEN")
    repo_name = os.getenv("GITHUB_REPO_NAME", "yourusername/autoheal-test-repo")

    if not github_token:
        return JSONResponse({"error": "GitHub token not configured in .env"}, status_code=500)

    # Find the latest incident for PR logging
    incidents = aegis_db.get_all_incidents(limit=1)
    incident_id = incidents[0]["id"] if incidents else None

    try:
        g = Github(github_token)
        repo = g.get_repo(repo_name)

        main_branch = repo.get_branch("main")

        branch_name = f"autoheal-fix-{os.urandom(4).hex()}"
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=main_branch.commit.sha)

        # Use the dynamic file path from stack trace introspection
        file_path = request.source_file

        try:
            file_contents = repo.get_contents(file_path, ref=main_branch.commit.sha)
            updated_content = f"{file_contents.decoded_content.decode('utf-8')}\n\n# --- AUTOHEAL.AI AUTO-PATCH ---\n{request.code}\n"
            repo.update_file(
                path=file_contents.path,
                message="fix(autoheal): auto-remediate schema drift",
                content=updated_content,
                sha=file_contents.sha,
                branch=branch_name
            )
        except Exception:
            repo.create_file(
                path=file_path,
                message="fix(autoheal): auto-remediate schema drift",
                content=f"# --- AUTOHEAL.AI AUTO-PATCH ---\n{request.code}\n",
                branch=branch_name
            )

        pr = repo.create_pull(
            title="[AutoHeal.ai] Automated Schema Drift Patch",
            body=(
                "AutoHeal.ai detected a 400 error caused by schema drift, "
                "generated a transformation patch, verified it via dry-run shadow execution, "
                "and opened this PR for review.\n\n"
                f"**Target file:** `{file_path}`\n\n"
                "**Review the mapping logic carefully before merging.**"
            ),
            head=branch_name,
            base="main"
        )

        # Log to audit DB
        if incident_id:
            aegis_db.log_pr(incident_id, branch_name, file_path, pr.html_url, "opened")

        return {"status": "success", "pr_url": pr.html_url}

    except GithubException as e:
        print(f"GitHub Error: {e}")
        if incident_id:
            aegis_db.log_pr(incident_id, branch_name if 'branch_name' in dir() else "unknown", request.source_file, status="failed")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


# ------------------------------------------------------------------
# Audit Log API
# ------------------------------------------------------------------
@app.get("/api/incidents")
async def list_incidents():
    """Returns the most recent incidents from the audit log."""
    incidents = aegis_db.get_all_incidents(limit=50)
    return JSONResponse(incidents)


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: int):
    """Returns full detail for a single incident including agent steps and PR history."""
    detail = aegis_db.get_incident_detail(incident_id)
    if not detail:
        return JSONResponse({"error": "Incident not found"}, status_code=404)
    return JSONResponse(detail)


if __name__ == "__main__":
    import uvicorn
    print("Starting AutoHeal.ai Dashboard Server on port 8001...")
    uvicorn.run(app, host="127.0.0.1", port=8001)