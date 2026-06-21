import os
import json
import asyncio
import sys
from fastapi import FastAPI
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from github import Github, GithubException

# Import the LangGraph builder from the agent file you just tested
from aegis_agent import build_aegis_graph

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
    This endpoint streams the LangGraph execution steps to the React frontend
    in real-time using Server-Sent Events (SSE).
    """
    async def event_generator():
        # 1. Simulate the Product Backend failure
        yield f"data: {json.dumps({'step': 'system', 'msg': 'User clicked Checkout. Initiating payment to Stripe API...'})}\n\n"
        await asyncio.sleep(1)
        
        old_cart_payload = {"user_id": 12345, "amount": 99.00}
        target_url = "http://127.0.0.1:8001/pay"
        error_details = "Schema Validation Failed: 'amount' and 'user_id' at the root level are deprecated. You must pass a nested 'transaction' object containing 'total_amount' and 'user_uuid'."
        
        # Stream the Crash
        yield f"data: {json.dumps({'step': 'error', 'msg': '🚨 HTTP 400 CAUGHT: Vendor schema drift detected.', 'payload': old_cart_payload})}\n\n"
        await asyncio.sleep(1.5)
        
        yield f"data: {json.dumps({'step': 'aegis_init', 'msg': '🛡️ Intercepted crash. Delegating to Aegis LangGraph Agent...'})}\n\n"
        
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
            "verification_status": "pending"
        }
        
        # 3. Stream the LangGraph nodes executing in real-time
        for event in graph.stream(initial_state):
            for node_name, state_update in event.items():
                if node_name == "diagnose":
                    yield f"data: {json.dumps({'step': 'node_llm', 'msg': '🧠 [Node 1: LLM] Diagnosing drift and generating patch...', 'code': state_update.get('generated_code')})}\n\n"
                elif node_name == "sandbox":
                    yield f"data: {json.dumps({'step': 'node_sandbox', 'msg': '🛠️ [Node 2: Sandbox] Executing AI code in restricted scope...', 'healed_payload': state_update.get('healed_payload')})}\n\n"
                elif node_name == "verify":
                    status = state_update.get('verification_status')
                    if status == 'success':
                         yield f"data: {json.dumps({'step': 'node_verify_success', 'msg': '🎉 [Node 3: Verification] Vendor accepted healed payload! Zero downtime achieved.'})}\n\n"
                    else:
                         yield f"data: {json.dumps({'step': 'node_verify_fail', 'msg': '⚠️ [Node 3: Verification] Vendor rejected payload. Looping back to LLM...'})}\n\n"
            
            await asyncio.sleep(0.8) # Slight delay so the UI animation looks cool for the judges
            
        yield f"data: {json.dumps({'step': 'done', 'msg': 'Process complete.'})}\n\n"
        
    return StreamingResponse(event_generator(), media_type="text/event-stream")

class PRRequest(BaseModel):
    code: str

@app.post("/api/approve-pr")
async def approve_and_create_pr(request: PRRequest):
    """
    Takes the AI generated code, pushes it to a new branch, and opens a Pull Request.
    """
    github_token = os.getenv("GITHUB_TOKEN")
    repo_name = os.getenv("GITHUB_REPO_NAME", "yourusername/aegis-test-repo") # e.g. "zantiti/aegis-demo"

    if not github_token:
        return {"error": "GitHub token not configured in .env"}, 500

    try:
        g = Github(github_token)
        repo = g.get_repo(repo_name)
        
        # Get the main branch to branch off from
        main_branch = repo.get_branch("main")
        
        # Create a unique branch name
        branch_name = f"aegis-auto-fix-{os.urandom(4).hex()}"
        repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=main_branch.commit.sha)

        # File we want to update in the repository
        file_path = "stripe_integration.py" 
        
        try:
            # Try to get the existing file content
            file_contents = repo.get_contents(file_path, ref=main_branch.commit.sha)
            
            # Append the AI's new mapping function to the file
            updated_content = f"{file_contents.decoded_content.decode('utf-8')}\n\n# --- AEGIS AUTO-PATCH ---\n{request.code}\n"
            
            repo.update_file(
                path=file_contents.path,
                message="chore(aegis): auto-heal schema drift",
                content=updated_content,
                sha=file_contents.sha,
                branch=branch_name
            )
        except Exception:
            # If the file doesn't exist, create it
            repo.create_file(
                path=file_path,
                message="chore(aegis): auto-heal schema drift",
                content=f"# --- AEGIS AUTO-PATCH ---\n{request.code}\n",
                branch=branch_name
            )

        # Create the actual Pull Request
        pr = repo.create_pull(
            title="🚨 [Aegis] Automated Schema Drift Patch",
            body="Aegis detected a 400 error schema drift, generated a patch, verified it via shadow execution, and opened this PR for review.\n\n**Review the mapping logic carefully before merging.**",
            head=branch_name,
            base="main"
        )
        
        return {"status": "success", "pr_url": pr.html_url}

    except GithubException as e:
        print(f"GitHub Error: {e}")
        return {"status": "error", "message": str(e)}, 500

if __name__ == "__main__":
    import uvicorn
    print("Starting Aegis Dashboard Server on port 8000...")
    uvicorn.run(app, host="127.0.0.1", port=8003)