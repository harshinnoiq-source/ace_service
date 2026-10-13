import json
import logging
import google.generativeai as genai
from cffi import model
from django.conf import settings
from urllib3 import response

logger = logging.getLogger(__name__)
genai.configure(api_key=settings.GEMINI_API_KEY)

def _build_prompt(metrics, user_answers, user_profile):
    return f"""
You are a diabetes care assistant. Based on the following CGM data and
lifestyle answers, generate a short, encouraging, non-diagnostic summary
and 2-3 practical suggestions. Do not give medical advice or diagnoses.

Patient profile: {json.dumps(user_profile)}
Glucose metrics (last {metrics['period']['days_available']} days): {json.dumps(metrics)}
Lifestyle answers: {json.dumps(user_answers)}

Respond ONLY as JSON in this format:
{{
  "summary": "...",
  "recommendations": ["...", "..."]
}}
"""

def generate_insights(metrics,user_answers,user_profile):
    model= genai.GenerativeModel("gemini-3.7-flash")
    prompt= _build_prompt(metrics,user_answers,user_profile)

    response=model.generate_content(prompt)
    text= response.text.strip()

    text=text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Gemini response was not valid Json,returning raw text")
        return {"summary":text,"recommendations":[]}

