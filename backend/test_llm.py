import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
genai.configure(api_key=api_key)

print("Starting LLM Test...")

try:
    # Initialize the 2.5 Flash model
    model = genai.GenerativeModel('gemini-2.5-flash')
    
    # Send a simple prompt
    response = model.generate_content("Say 'Aegis Systems are online!' if you can hear me.")
    
    print("\n✅ SUCCESS! Gemini responded with:")
    print(response.text)
    
except Exception as e:
    print(f"\n❌ ERROR: Something went wrong. {e}")