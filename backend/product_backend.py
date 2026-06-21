import httpx

def checkout():
    """
    Simulates your main E-commerce Backend trying to process an order.
    """
    print("\n[Product Backend] User clicked Checkout. Initiating payment...")
    
    # This is the OLD payload format that our product currently uses.
    # We don't know the vendor changed their rules overnight!
    old_cart_payload = {
        "user_id": 12345,
        "amount": 99.00
    }
    
    target_url = "http://127.0.0.1:8001/pay"

    try:
        # We attempt the HTTP request to the vendor
        response = httpx.post(target_url, json=old_cart_payload)
        
        # This raises an exception if the status code is 4xx or 5xx
        response.raise_for_status() 
        
        print("[Product Backend] Order placed successfully!")
        return response.json()
        
    except httpx.HTTPStatusError as e:
        # THE TRAP: We catch the HTTP error instead of letting the app crash!
        if e.response.status_code == 400:
            error_details = e.response.json().get('detail', e.response.text)
            print(f"\n[Product Backend] 🚨 CAUGHT 400 ERROR from Vendor!")
            print(f"Error Message: {error_details}")
            
            # Here is where we will eventually call our Aegis Agent
            print("\n[Product Backend] 🛡️ Delegating payload and error to Aegis Remediation API...")
            
            # For now, we just return a placeholder so the app doesn't crash
            return {"status": "delegated_to_aegis"}
        else:
            # If it's a 500 server down error, we can't heal that.
            print(f"[Product Backend] Fatal error {e.response.status_code}")
            raise

if __name__ == "__main__":
    # Run the checkout simulation
    checkout()