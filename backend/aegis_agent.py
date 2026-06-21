import os
import copy
import httpx
import sys
from typing import TypedDict, Optional
from pydantic import BaseModel, Field

# LangGraph & LangChain Imports
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from dotenv import load_dotenv

# Avoid unicode encode errors on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

load_dotenv()

# ==========================================
# 1. DEFINE THE AGENT'S STATE MEMORY
# ==========================================
# This acts as the shared memory passed between the nodes
class AgentState(TypedDict):
    original_payload: dict
    current_error: str
    target_url: str
    retry_count: int
    max_retries: int
    generated_code: Optional[str]
    healed_payload: Optional[dict]
    verification_status: str  # "pending", "success", "failed"

# ==========================================
# 2. STRUCTURED LLM OUTPUT
# ==========================================
# We use Pydantic to ensure the LLM returns exact JSON format
class AgentPatchResponse(BaseModel):
    reasoning: str = Field(description="Step-by-step logic explaining schema drift.")
    python_code: str = Field(description="A Python function named 'transform_payload(data)' returning the corrected dictionary. No markdown, just raw code.")

# ==========================================
# 3. DEFINE THE GRAPH NODES
# ==========================================
class AegisLangGraph:
    def __init__(self):
        # Initialize Gemini 2.5 Flash via LangChain
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.1, # Low temperature for more deterministic code generation
            api_key=os.getenv("GEMINI_API_KEY")
        )
        # Bind our Pydantic schema so the LLM output is strictly parsed
        self.structured_llm = self.llm.with_structured_output(AgentPatchResponse)

    def node_diagnose_and_generate(self, state: AgentState) -> AgentState:
        """Node 1: Analyzes the error and writes the Python patch."""
        print(f"\n[Node: LLM] 🧠 Diagnosing drift (Attempt {state['retry_count'] + 1})...")
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an autonomous API remediation agent. Fix the payload to match the vendor error. Write a Python function `transform_payload(data)` that returns the valid JSON dict. Note: Watch for type changes (e.g., casting integer IDs to strings)."),
            ("human", "FAILED PAYLOAD: {payload}\nVENDOR ERROR: {error}")
        ])
        
        chain = prompt | self.structured_llm
        result: AgentPatchResponse = chain.invoke({
            "payload": state["original_payload"], 
            "error": state["current_error"]
        })
        
        print(f"[Node: LLM] 💡 Reasoning: {result.reasoning}")
        return {"generated_code": result.python_code}

    def node_sandbox_execution(self, state: AgentState) -> AgentState:
        """Node 2: Safely executes the generated code in an isolated scope."""
        print("[Node: Sandbox] 🛠️ Executing AI code in restricted scope...")
        local_scope = {}
        try:
            # Execute the AI code in isolation
            exec(state["generated_code"], {}, local_scope)
            
            # Run the AI's function against a deep copy of the original data to prevent mutations
            healed = local_scope['transform_payload'](copy.deepcopy(state["original_payload"]))
            print(f"[Node: Sandbox] ✅ Payload transformed: {healed}")
            
            # Clear error if successful
            return {"healed_payload": healed, "current_error": None} 
        except Exception as e:
            print(f"[Node: Sandbox] ❌ Execution crashed: {e}")
            return {"current_error": f"Sandbox Code Execution Error: {str(e)}", "healed_payload": None}

    def node_shadow_verification(self, state: AgentState) -> AgentState:
        """Node 3: Replays the HTTP request to the target API to verify the fix."""
        print(f"[Node: Verification] 🔄 Replaying shadow request to {state['target_url']}...")
        try:
            res = httpx.post(state["target_url"], json=state["healed_payload"])
            res.raise_for_status()
            print("[Node: Verification] 🎉 Vendor accepted the healed payload!")
            return {"verification_status": "success", "healed_payload": state["healed_payload"]}
        except httpx.HTTPStatusError as e:
            new_error = e.response.json().get('detail', e.response.text)
            print(f"[Node: Verification] ⚠️ Vendor rejected payload again: {new_error}")
            return {"verification_status": "failed", "current_error": new_error}

# ==========================================
# 4. DEFINE CONDITIONAL ROUTING (EDGES)
# ==========================================
def should_verify_or_retry(state: AgentState) -> str:
    """Decides where to go after the Sandbox completes."""
    if state["current_error"] is not None:
        # Sandbox crashed. Do we retry?
        if state["retry_count"] < state["max_retries"]:
            state["retry_count"] += 1
            return "retry_generation"
        return "end"
    # Sandbox succeeded, move to HTTP verification
    return "verify_shadow_run"

def check_verification_status(state: AgentState) -> str:
    """Decides where to go after Vendor Verification."""
    if state["verification_status"] == "success":
        return "end"
    if state["retry_count"] < state["max_retries"]:
        state["retry_count"] += 1
        return "retry_generation"
    return "end"

# ==========================================
# 5. COMPILE THE LANGGRAPH
# ==========================================
def build_aegis_graph():
    aegis = AegisLangGraph()
    workflow = StateGraph(AgentState)

    # Add our nodes to the graph
    workflow.add_node("diagnose", aegis.node_diagnose_and_generate)
    workflow.add_node("sandbox", aegis.node_sandbox_execution)
    workflow.add_node("verify", aegis.node_shadow_verification)

    # Define the flow (Edges)
    workflow.set_entry_point("diagnose")
    workflow.add_edge("diagnose", "sandbox")
    
    # Conditional Edges
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
# 6. EXTERNAL API EXPOSED TO PRODUCT BACKEND
# ==========================================
def heal_and_retry(failed_payload: dict, error_msg: str, target_url: str) -> dict:
    """
    Initializes the graph state and triggers the autonomous healing workflow.
    Called directly by `product_backend.py`.
    """
    graph = build_aegis_graph()
    
    initial_state = {
        "original_payload": failed_payload,
        "current_error": error_msg,
        "target_url": target_url,
        "retry_count": 0,
        "max_retries": 2, # It will try up to 3 times total (initial + 2 retries)
        "generated_code": None,
        "healed_payload": None,
        "verification_status": "pending"
    }

    print("\n[Aegis Graph] 🚀 Starting Autonomous Agentic Workflow...")
    
    # Invoke the LangGraph state machine
    final_state = graph.invoke(initial_state)

    if final_state["verification_status"] == "success":
        # Graph succeeded. Do the final HTTP request to return to the user.
        retry_response = httpx.post(target_url, json=final_state["healed_payload"])
        return retry_response.json()
    else:
        # Graph exhausted retries
        raise Exception(f"Agent exhausted retries and failed to heal the payload. Last error: {final_state['current_error']}")