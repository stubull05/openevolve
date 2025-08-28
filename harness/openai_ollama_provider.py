import os
from openai import OpenAI
import yfinance as yf
from datetime import datetime
import pytz

class OpenAIOllamaProvider:
    """AI provider using Ollama with optional market context."""
    def __init__(self):
        base_url = os.getenv('OLLAMA_BASE_URL', 'http://host.docker.internal:11434/v1')
        self.client = OpenAI(base_url=base_url, api_key='ollama')
        self.model = os.getenv('OLLAMA_MODEL', 'codellama:7b')
        print(f"[OpenAIOllama] Base URL: {base_url} | Model: {self.model}")
    
    def get_market_data(self, symbols):
        market_data = []
        for symbol in symbols[:3]:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period='1d')
                info = getattr(ticker, 'info', {}) or {}
                if not hist.empty:
                    current_price = float(hist['Close'].iloc[-1])
                    prev_close = float(info.get('previousClose', current_price))
                    change = current_price - prev_close
                    change_pct = (change / prev_close * 100.0) if prev_close else 0.0
                    market_data.append(f"{symbol}: ${current_price:.2f} ({change_pct:+.1f}%)")
            except Exception:
                continue
        return "; ".join(market_data) if market_data else None

    def get_stream(self, prompt: str, history: list = []):
        try:
            et = pytz.timezone('America/New_York')
            now = datetime.now(et)
            system_content = (
                f"You are a trading assistant. Today is {now.strftime('%Y-%m-%d')} and the current time is {now.strftime('%H:%M')} ET.\nBe concise and practical."
            )
            messages = [{"role":"system","content":system_content}]
            for msg in history[-5:]:
                messages.append(msg)
            messages.append({"role":"user","content":prompt})
            stream = self.client.chat.completions.create(
                model=self.model, messages=messages, stream=True, temperature=0.7, max_tokens=300
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content is not None:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            print(f"[OpenAIOllama] Error: {e}")
            yield "Error: Ollama server not available. Ensure 'ollama serve' is running on host."
