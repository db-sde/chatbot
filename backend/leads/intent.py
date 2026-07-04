from __future__ import annotations

import json
import logging
from typing import Any

from agent.llm_client import llm_client

logger = logging.getLogger(__name__)

# Configurable lead intent confidence threshold
LEAD_INTENT_CONFIDENCE_THRESHOLD = 0.80

async def lead_intent_classifier(session_id: str, user_message: str, history_messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Uses the LLM to classify user message intent semantically.
    
    Returns:
      {
        "lead_intent": bool,
        "confidence": float,
        "intent_type": str,
        "reasoning": str
      }
    """
    if not llm_client.enabled:
        return {
            "lead_intent": False,
            "confidence": 0.0,
            "intent_type": "none",
            "reasoning": "LLM disabled"
        }

    # Format history messages for context
    history_str = ""
    for msg in history_messages[-6:]:  # recent 6 turns for context
        role = msg.get("role", "user")
        content = msg.get("content", "")
        history_str += f"{role.upper()}: {content}\n"

    prompt = f"""You are an advanced SaaS Lead Intent Classifier for DegreeBaba, an AI educational advisor.
Your job is to semantically analyze the latest message from a student within the conversation context to determine if they are expressing intent that warrants human counsellor outreach/callback.

[INSTRUCTIONS]
Classify the user's intent into one of these categories:
1. "human_advisor_request" - The student explicitly or implicitly wants to speak with a human, counsellor, advisor, representative, or get a callback.
2. "admission_guidance" - The student needs personalized help selecting a course/university, or application/registration steps.
3. "career_counselling" - The student is asking about career choices, placement scope, or choosing a specialization.
4. "scholarship_support" - The student is seeking information/help with scholarships, fee discounts, or loan/financial assistance.
5. "none" - None of the above (simple greetings, generic questions about facts already resolved by facts, or out of topic chatter).

Analyze the meaning semantically, accounting for Hinglish, spelling errors, mixed language (English/Hindi), and indirect phrasing.
Examples of high intent:
- "Can you connect me to admission department?"
- "koi call kar sakta hai mujhe?" (Hinglish)
- "mujhe admission guide chahiye"
- "ready to join if scholarship is there"
- "unable to choose between NMIMS and Amity, need advice"
- "call me on 9876543210"

[CONVERSATION HISTORY]
{history_str}
LATEST USER MESSAGE: "{user_message}"

[RESPONSE FORMAT]
Respond ONLY with a raw JSON object. Do not include markdown code block tags or extra explanation.
JSON Schema:
{{
  "lead_intent": true or false,
  "confidence": <float between 0.0 and 1.0>,
  "intent_type": "human_advisor_request" | "admission_guidance" | "career_counselling" | "scholarship_support" | "none",
  "reasoning": "<concise sentence explaining classification>"
}}
"""
    try:
        res = await llm_client.generate_json(prompt)
        
        # Parse output safely and validate keys
        lead_intent = bool(res.get("lead_intent", False))
        confidence = float(res.get("confidence", 0.0))
        intent_type = str(res.get("intent_type", "none"))
        reasoning = str(res.get("reasoning", ""))
        
        return {
            "lead_intent": lead_intent,
            "confidence": confidence,
            "intent_type": intent_type,
            "reasoning": reasoning
        }
    except Exception as exc:
        logger.exception("Error executing lead_intent_classifier (session=%s): %s", session_id, exc)
        return {
            "lead_intent": False,
            "confidence": 0.0,
            "intent_type": "none",
            "reasoning": f"Classifier error: {exc}"
        }
