#!/usr/bin/env python3
import requests
import json

def test_ollama():
    endpoints = [
        "http://localhost:11434",
        "http://host.docker.internal:11434", 
        "http://127.0.0.1:11434"
    ]
    
    for endpoint in endpoints:
        print(f"Testing: {endpoint}")
        
        try:
            response = requests.get(f"{endpoint}/api/tags", timeout=5)
            if response.status_code == 200:
                models = response.json()
                print(f"SUCCESS! Found {len(models.get('models', []))} models")
                
                # Test chat
                chat_data = {
                    "model": "qwen2.5-coder:7b",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "stream": False
                }
                
                chat_response = requests.post(f"{endpoint}/v1/chat/completions", json=chat_data, timeout=30)
                
                if chat_response.status_code == 200:
                    result = chat_response.json()
                    content = result['choices'][0]['message']['content']
                    print(f"Chat works! Response: {content[:50]}...")
                    return endpoint
                else:
                    print(f"Chat failed: {chat_response.status_code}")
                    
        except Exception as e:
            print(f"Failed: {str(e)}")
    
    return None

if __name__ == "__main__":
    working = test_ollama()
    if working:
        print(f"Use endpoint: {working}/v1")
    else:
        print("No working endpoint found")