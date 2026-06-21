"""
AutoHeal.ai - LangGraph Agent v2
- Enhanced structured output (old_schema, new_schema, old_code, new_code)
- Mock LangChain @tool for fetching vendor documentation
- Safe dry-run shadow verification with idempotency headers
- Stack trace introspection for dynamic PR file targeting
- SQLite audit logging for every step
"""
import os
import copy
import httpx
import sys
import json
import traceback
import time
from uuid import uuid4
from typing import TypedDict, Optional
from pydantic import BaseModel, Field

# LangGraph & LangChain Imports
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from dotenv import load_dotenv

import aegis_db

# Avoid unicode encode errors on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

# ==========================================
# MOCK TOOL: Vendor Documentation Lookup
# ==========================================
@tool
def fetch_vendor_documentation(api_name: str) -> str:
    """Fetches the latest OpenAPI schema snippet for a vendor API.
    Use this tool when the error message is ambiguous and you need
    to understand the exact required request body format."""
    docs = {
        "stripe": json.dumps({
            "openapi": "3.0.0",
            "paths": {
                "/pay": {
                    "post": {
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["transaction"],
                                        "properties": {
                                            "transaction": {
                                                "type": "object",
                                                "required": ["total_amount", "user_uuid"],
                                                "properties": {
                                                    "total_amount": {"type": "number"},
                                                    "user_uuid": {"type": "string", "format": "uuid"}
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }, indent=2)
    }
    return docs.get(api_name.lower(), f"No documentation found for '{api_name}'.")


# ==========================================
# STACK TRACE INTROSPECTION
# ==========================================
def introspect_caller_file() -> str:
    """Walks the call stack to find the source file that initiated the API call.
    Falls back to 'integrations/stripe_integration.py' if no match is found."""
    stack = traceback.extract_stack()
    for frame in reversed(stack):
        fname = frame.filename.replace("\\", "/")
        # Skip internal framework files and this agent file
        if any(skip in fname for skip in ["aegis_agent", "langgraph", "langchain", "server.py", "uvicorn", "fastapi", "starlette"]):
            continue
        if fname.endswith(".py"):
            # Return a repo-relative path
            parts = fname.split("/")
            if "backend" in parts:
                idx = parts.index("backend")
                return "/".join(parts[idx:])
            return os.path.basename(fname)
    return "integrations/stripe_integration.py"


# ==========================================
# 1. AGENT STATE MEMORY
# ==========================================
class AgentState(TypedDict):
    original_payload: dict
    current_error: str
    target_url: str
    retry_count: int
    max_retries: int
    generated_code: Optional[str]
    healed_payload: Optional[dict]
    verification_status: str       # "pending", "success", "failed"
    # v2 additions
    old_schema: Optional[str]
    new_schema: Optional[str]
    old_code: Optional[str]
    new_code: Optional[str]
    source_file: Optional[str]
    vendor_docs: Optional[str]
    incident_id: Optional[int]


# ==========================================
# 2. STRUCTURED LLM OUTPUT
# ==========================================
class AgentPatchResponse(BaseModel):
    reasoning: str = Field(description="Step-by-step logic explaining the schema drift and how the patch resolves it.")
    old_schema: str = Field(description="JSON representation of the original failed payload structure, e.g. {\"user_id\": \"int\", \"amount\": \"float\"}")
    new_schema: str = Field(description="JSON representation of the corrected payload structure required by the vendor.")
    old_code: str = Field(description="A Python function named 'format_payload(data)' representing the deprecated integration code that produced the old payload.")
    new_code: str = Field(description="A Python function named 'transform_payload(data)' that converts the old payload to the new required schema. No markdown, just raw executable Python code.")


# ==========================================
# 3. GRAPH NODES
# ==========================================
class AegisLangGraph:
    def __init__(self):
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.1,
            api_key=os.getenv("GEMINI_API_KEY")
        )
        self.structured_llm = self.llm.with_structured_output(AgentPatchResponse)

    def node_fetch_docs(self, state: AgentState) -> AgentState:
        """Node 0 (optional): Fetches vendor documentation for additional context."""
        print("[Node: Tool] Fetching vendor documentation...")
        docs = fetch_vendor_documentation.invoke("stripe")
        print(f"[Node: Tool] Retrieved OpenAPI snippet ({len(docs)} chars)")

        if state.get("incident_id"):
            aegis_db.log_agent_step(
                incident_id=state["incident_id"],
                step_name="fetch_docs",
                attempt=state["retry_count"] + 1,
                reasoning="Fetched vendor OpenAPI documentation for schema reference."
            )
        return {"vendor_docs": docs}

    def node_diagnose_and_generate(self, state: AgentState) -> AgentState:
        """Node 1: Analyzes the error and writes the Python patch."""
        attempt = state['retry_count'] + 1
        print(f"\n[Node: LLM] Diagnosing drift (Attempt {attempt})...")

        vendor_context = ""
        if state.get("vendor_docs"):
            vendor_context = f"\nVENDOR OPENAPI DOCUMENTATION:\n{state['vendor_docs']}"

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "You are an autonomous API remediation agent (Project Aegis). "
             "Analyze the failed payload and vendor error to produce a complete patch. "
             "You must return: reasoning, old_schema (JSON of old structure), new_schema (JSON of new structure), "
             "old_code (a Python function `format_payload(data)` that represents the deprecated code), "
             "and new_code (a Python function `transform_payload(data)` that maps old to new). "
             "For user_uuid: generate a deterministic UUID from user_id using uuid.uuid5. "
             "For total_amount: map from amount. Nest everything under a 'transaction' key."),
            ("human",
             "FAILED PAYLOAD: {payload}\n"
             "VENDOR ERROR: {error}"
             "{vendor_docs}")
        ])

        chain = prompt | self.structured_llm
        
        # Exponential backoff retry loop for Gemini API rate limits (HTTP 429)
        max_api_retries = 5
        backoff_seconds = 2
        for api_attempt in range(max_api_retries):
            try:
                result: AgentPatchResponse = chain.invoke({
                    "payload": state["original_payload"],
                    "error": state["current_error"],
                    "vendor_docs": vendor_context
                })
                break
            except Exception as e:
                err_str = str(e)
                is_rate_limit = "429" in err_str or "ResourceExhausted" in err_str or "quota" in err_str.lower() or "limit" in err_str.lower()
                if is_rate_limit and api_attempt < max_api_retries - 1:
                    print(f"[Node: LLM] Gemini rate limit hit (429). Retrying in {backoff_seconds}s...")
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2
                else:
                    print(f"[Node: LLM] API call failed on attempt {api_attempt + 1}: {e}")
                    raise e

        print(f"[Node: LLM] Reasoning: {result.reasoning}")

        if state.get("incident_id"):
            aegis_db.log_agent_step(
                incident_id=state["incident_id"],
                step_name="diagnose",
                attempt=attempt,
                reasoning=result.reasoning,
                old_schema=json.loads(result.old_schema) if result.old_schema else None,
                new_schema=json.loads(result.new_schema) if result.new_schema else None,
                old_code=result.old_code,
                new_code=result.new_code
            )

        return {
            "generated_code": result.new_code,
            "old_schema": result.old_schema,
            "new_schema": result.new_schema,
            "old_code": result.old_code,
            "new_code": result.new_code,
        }

    def node_sandbox_execution(self, state: AgentState) -> AgentState:
        """Node 2: Safely executes the generated code in an isolated scope."""
        print("[Node: Sandbox] Executing AI code in restricted scope...")
        local_scope = {}
        # Provide safe standard library modules so LLM-generated code can use them
        import uuid as _uuid
        import json as _json
        import math as _math
        safe_globals = {
            "__builtins__": {"__import__": __import__, "str": str, "int": int, "float": float,
                             "dict": dict, "list": list, "tuple": tuple, "bool": bool,
                             "len": len, "range": range, "print": print, "isinstance": isinstance,
                             "round": round, "abs": abs, "min": min, "max": max, "sorted": sorted,
                             "enumerate": enumerate, "zip": zip, "map": map, "filter": filter},
            "uuid": _uuid,
            "json": _json,
            "math": _math,
        }
        try:
            exec(state["generated_code"], safe_globals, local_scope)
            healed = local_scope['transform_payload'](copy.deepcopy(state["original_payload"]))
            print(f"[Node: Sandbox] Payload transformed: {healed}")

            if state.get("incident_id"):
                aegis_db.log_agent_step(
                    incident_id=state["incident_id"],
                    step_name="sandbox",
                    attempt=state["retry_count"] + 1,
                    healed_payload=healed,
                    verification="execution_success"
                )

            return {"healed_payload": healed, "current_error": None}
        except Exception as e:
            print(f"[Node: Sandbox] Execution crashed: {e}")

            if state.get("incident_id"):
                aegis_db.log_agent_step(
                    incident_id=state["incident_id"],
                    step_name="sandbox",
                    attempt=state["retry_count"] + 1,
                    verification="execution_failed",
                    error_detail=str(e)
                )

            return {"current_error": f"Sandbox Code Execution Error: {str(e)}", "healed_payload": None}

    def node_shadow_verification(self, state: AgentState) -> AgentState:
        """Node 3: Replays the HTTP request as a DRY-RUN to verify the fix."""
        print(f"[Node: Verification] Replaying DRY-RUN shadow request to {state['target_url']}...")
        dry_run_headers = {
            "X-Dry-Run": "true",
            "Idempotency-Key": f"aegis-shadow-{uuid4().hex[:8]}"
        }
        try:
            res = httpx.post(state["target_url"], json=state["healed_payload"], headers=dry_run_headers)
            res.raise_for_status()
            print("[Node: Verification] Vendor accepted the healed payload (dry-run)!")

            if state.get("incident_id"):
                aegis_db.log_agent_step(
                    incident_id=state["incident_id"],
                    step_name="verify",
                    attempt=state["retry_count"] + 1,
                    healed_payload=state["healed_payload"],
                    verification="dry_run_success"
                )
                aegis_db.update_incident_status(state["incident_id"], "healed")

            return {"verification_status": "success", "healed_payload": state["healed_payload"]}
        except Exception as e:
            if isinstance(e, httpx.HTTPStatusError):
                try:
                    new_error = e.response.json().get('detail', e.response.text)
                except Exception:
                    new_error = e.response.text
            else:
                new_error = f"Connection/Request Error: {str(e)}"
            print(f"[Node: Verification] Vendor rejected payload or request failed: {new_error}")

            if state.get("incident_id"):
                aegis_db.log_agent_step(
                    incident_id=state["incident_id"],
                    step_name="verify",
                    attempt=state["retry_count"] + 1,
                    verification="dry_run_failed",
                    error_detail=new_error
                )

            return {"verification_status": "failed", "current_error": new_error}


# ==========================================
# 4. CONDITIONAL ROUTING (EDGES)
# ==========================================
def should_verify_or_retry(state: AgentState) -> str:
    if state["current_error"] is not None:
        if state["retry_count"] < state["max_retries"]:
            state["retry_count"] += 1
            print(f"[Graph] Sandbox/validation error detected: '{state['current_error']}'. Sleeping 1.5s before retrying...")
            time.sleep(1.5)
            return "retry_generation"
        return "end"
    return "verify_shadow_run"


def check_verification_status(state: AgentState) -> str:
    if state["verification_status"] == "success":
        return "end"
    if state["retry_count"] < state["max_retries"]:
        state["retry_count"] += 1
        print("[Graph] Verification failed. Sleeping 1.5s before retrying...")
        time.sleep(1.5)
        return "retry_generation"
    return "end"


# ==========================================
# 5. COMPILE THE LANGGRAPH
# ==========================================
def build_aegis_graph():
    aegis = AegisLangGraph()
    workflow = StateGraph(AgentState)

    workflow.add_node("fetch_docs", aegis.node_fetch_docs)
    workflow.add_node("diagnose", aegis.node_diagnose_and_generate)
    workflow.add_node("sandbox", aegis.node_sandbox_execution)
    workflow.add_node("verify", aegis.node_shadow_verification)

    workflow.set_entry_point("fetch_docs")
    workflow.add_edge("fetch_docs", "diagnose")
    workflow.add_edge("diagnose", "sandbox")

    workflow.add_conditional_edges(
        "sandbox",
        should_verify_or_retry,
        {
            "verify_shadow_run": "verify",
            "retry_generation": "diagnose",
            "end": END
        }
    )
    workflow.add_conditional_edges(
        "verify",
        check_verification_status,
        {
            "retry_generation": "diagnose",
            "end": END
        }
    )

    return workflow.compile()


# ==========================================
# 6. EXTERNAL API
# ==========================================
def heal_and_retry(failed_payload: dict, error_msg: str, target_url: str) -> dict:
    """
    Initializes the graph state and triggers the autonomous healing workflow.
    Called directly by `product_backend.py`.
    """
    source_file = introspect_caller_file()
    incident_id = aegis_db.create_incident(target_url, failed_payload, error_msg, source_file)

    graph = build_aegis_graph()

    initial_state = {
        "original_payload": failed_payload,
        "current_error": error_msg,
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

    print(f"\n[Aegis Graph] Starting Autonomous Agentic Workflow (Incident #{incident_id})...")

    final_state = graph.invoke(initial_state)

    if final_state["verification_status"] == "success":
        retry_response = httpx.post(target_url, json=final_state["healed_payload"])
        return retry_response.json()
    else:
        aegis_db.update_incident_status(incident_id, "failed")
        raise Exception(f"Agent exhausted retries. Last error: {final_state['current_error']}")