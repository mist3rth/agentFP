import os
from google import genai
from google.genai import types

def check_rule(rule_id: str) -> str:
    return "ok"

client = genai.Client()
chat = client.chats.create(
    model="gemini-flash-lite-latest",
    config=types.GenerateContentConfig(tools=[check_rule])
)
response = chat.send_message("Call check_rule with rule_id='test'. Then reply 'Done'.")
print("Response text:", response.text)
