from __future__ import annotations

# Pricing config for LLMs, price per million tokens in USD
MODEL_PRICING = {
    # Gemini 2.5 Flash
    "gemini-2.5-flash": {
        "input_per_million": 0.075,
        "output_per_million": 0.30
    },
    # Gemini 1.5 Flash (fallback config)
    "gemini-1.5-flash": {
        "input_per_million": 0.075,
        "output_per_million": 0.30
    },
    # Llama 3.3 70B Versatile on Groq
    "llama-3.3-70b-versatile": {
        "input_per_million": 0.59,
        "output_per_million": 0.79
    },
    # Default fallback pricing
    "default": {
        "input_per_million": 0.15,
        "output_per_million": 0.60
    }
}

def calculate_message_cost(model_name: str | None, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """Calculate the estimated USD cost of an LLM turn.
    
    If input_tokens or output_tokens are missing/None, returns None.
    Does a partial/case-insensitive substring check to find the closest match.
    """
    if input_tokens is None or output_tokens is None:
        return None
    
    model_name = (model_name or "default").lower()
    
    # Try exact match first
    cfg = MODEL_PRICING.get(model_name)
    
    if not cfg:
        # Try partial match (e.g. "gemini-2.5-flash" inside "gemini-2.5-flash-latest")
        for key, val in MODEL_PRICING.items():
            if key != "default" and key in model_name:
                cfg = val
                break
                
    if not cfg:
        cfg = MODEL_PRICING["default"]
        
    input_cost = (input_tokens / 1_000_000.0) * cfg["input_per_million"]
    output_cost = (output_tokens / 1_000_000.0) * cfg["output_per_million"]
    
    return round(input_cost + output_cost, 8)
