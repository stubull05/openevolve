#!/usr/bin/env python3
"""
Test Ollama connection from within a Docker container context.
"""

import requests
import json

def test_ollama_connection():
    """Test Ollama API connection and model availability."""
    
    # Test endpoints to try
    endpoints = [
        "http://localhost:11434",
        "http://host.docker.internal:11434", 
        "http://127.0.0.1:11434"
    ]
    
    for endpoint in endpoints:
        print(f"Testing endpoint: {endpoint}")
        
        try:
            # Test basic connection
            response = requests.get(f"{endpoint}/api/tags", timeout=5)
            if response.status_code == 200:
                models = response.json()
                print(f"✅ Connected! Found {len(models.get('models', []))} models")
                
                # Test chat completion
                chat_data = {
                    "model": "qwen2.5-coder:7b",
                    "messages": [
                        {"role": "user", "content": "Write a simple hello function in JavaScript"}
                    ],
                    "stream": False
                }
                
                chat_response = requests.post(
                    f"{endpoint}/v1/chat/completions", 
                    json=chat_data,
                    timeout=30
                )
                
                if chat_response.status_code == 200:
                    result = chat_response.json()
                    content = result['choices'][0]['message']['content']
                    print(f"✅ Chat API works! Response: {content[:100]}...")
                    return endpoint
                else:
                    print(f"❌ Chat API failed: {chat_response.status_code}")
                    
        except Exception as e:
            print(f"❌ Failed: {e}")
    
    return None

if __name__ == "__main__":
    working_endpoint = test_ollama_connection()
    if working_endpoint:
        print(f"\n🎉 Use this endpoint: {working_endpoint}/v1")
    else:
        print("\n❌ No working Ollama endpoint found")