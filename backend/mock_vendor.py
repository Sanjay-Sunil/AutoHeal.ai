from fastapi import FastAPI, HTTPException, Request
import uvicorn

app = FastAPI()

@app.post("/pay")
async def process_payment(request: Request):
    """
    Simulates a 3rd party vendor API (like Stripe).
    Imagine they just updated their API version overnight.
    """
    payload = await request.json()
    print(f"[Vendor API] Received payload: {payload}")

    # The new strict schema requirement! 
    # It now expects {"transaction": {"total_amount": 100}}
    if "transaction" not in payload or "total_amount" not in payload.get("transaction", {}):
        error_msg = (
            "Schema Validation Failed: 'amount' and 'user_id' at the root level "
            "are deprecated. You must pass a nested 'transaction' object containing "
            "'total_amount' and 'user_uuid'."
        )
        print(f"[Vendor API] ❌ Rejecting request with 400. Reason: {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)

    print("[Vendor API] ✅ Payment Processed Successfully!")
    return {"status": "success", "transaction_id": "txn_987654321"}

if __name__ == "__main__":
    # Runs the vendor API on port 8001
    print("Starting Mock Vendor API on port 8001...")
    uvicorn.run(app, host="127.0.0.1", port=8001)