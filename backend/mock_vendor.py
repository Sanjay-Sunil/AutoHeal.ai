"""
Mock Vendor API (Simulates Stripe-like 3rd Party Service)
- Validates the new nested 'transaction' schema
- Supports X-Dry-Run header for safe shadow verification
"""
from fastapi import FastAPI, HTTPException, Request
import uvicorn
import sys

# Avoid unicode encode errors on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

app = FastAPI()


@app.post("/pay")
async def process_payment(request: Request):
    """
    Simulates a 3rd party vendor API (like Stripe).
    Imagine they just updated their API version overnight.
    """
    payload = await request.json()
    is_dry_run = request.headers.get("X-Dry-Run", "").lower() == "true"
    idempotency_key = request.headers.get("Idempotency-Key", None)

    mode_label = "DRY-RUN" if is_dry_run else "LIVE"
    print(f"[Vendor API] [{mode_label}] Received payload: {payload}")
    if idempotency_key:
        print(f"[Vendor API] Idempotency-Key: {idempotency_key}")

    # The new strict schema requirement!
    # It now expects {"transaction": {"total_amount": 100, "user_uuid": "..."}}
    transaction = payload.get("transaction", {})
    if (not isinstance(payload, dict)
            or "transaction" not in payload
            or not isinstance(transaction, dict)
            or "total_amount" not in transaction
            or "user_uuid" not in transaction):
        error_msg = (
            "Schema Validation Failed: 'amount' and 'user_id' at the root level "
            "are deprecated. You must pass a nested 'transaction' object containing "
            "'total_amount' and 'user_uuid'."
        )
        print(f"[Vendor API] Rejecting request with 400. Reason: {error_msg}")
        raise HTTPException(status_code=400, detail=error_msg)

    # Schema is valid
    if is_dry_run:
        print("[Vendor API] Schema validated (Dry-Run). No payment processed.")
        return {
            "status": "dry_run_success",
            "message": "Schema validated. No payment processed.",
            "idempotency_key": idempotency_key
        }

    print("[Vendor API] Payment Processed Successfully!")
    return {"status": "success", "transaction_id": "txn_987654321"}


if __name__ == "__main__":
    # Runs the vendor API on port 8001
    print("Starting Mock Vendor API on port 8000...")
    uvicorn.run(app, host="127.0.0.1", port=8000)