from dotenv import load_dotenv
from openai import OpenAI
from html import escape
import json
import os
import requests
from pypdf import PdfReader
import gradio as gr

load_dotenv(override=True)

# Empfänger der Benachrichtigungen (kann im Space als Secret NOTIFY_EMAIL überschrieben werden)
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "ayadi.achraf2@gmail.com")


# ---------------------------------------------------------------------------
# E-Mail-Versand über Mailgun
# ---------------------------------------------------------------------------
def send_email(subject, html_body, reply_to=None):
    """Sendet eine E-Mail über Mailgun. Gibt True/False zurück, Fehler landen im Log."""
    domain = os.getenv("MAILGUN_DOMAIN")
    api_key = os.getenv("MAILGUN_API_KEY")
    base_url = os.getenv("MAILGUN_BASE_URL", "https://api.mailgun.net").rstrip("/")
    if not domain or not api_key:
        print("Mailgun: MAILGUN_DOMAIN oder MAILGUN_API_KEY fehlt", flush=True)
        return False

    data = {
        "from": f"Portfolio KI-Agent <postmaster@{domain}>",
        "to": f"Achraf <{NOTIFY_EMAIL}>",
        "subject": subject,
        "html": html_body,
    }
    if reply_to:
        data["h:Reply-To"] = reply_to

    try:
        response = requests.post(
            f"{base_url}/v3/{domain}/messages",
            auth=("api", api_key),
            data=data,
            timeout=20,
        )
        print(f"Mailgun: {response.status_code} {response.text[:200]}", flush=True)
        return response.ok
    except requests.RequestException as e:
        print(f"Mailgun: Fehler beim Senden: {e}", flush=True)
        return False


def _email_layout(title, rows, transcript):
    """Einfaches, gut lesbares HTML für die Benachrichtigungen."""
    rows_html = "".join(
        f"<tr><td style='padding:6px 12px 6px 0;color:#666;vertical-align:top'>{escape(k)}</td>"
        f"<td style='padding:6px 0;white-space:pre-wrap'>{escape(v)}</td></tr>"
        for k, v in rows
        if v
    )
    transcript_html = ""
    if transcript:
        transcript_html = (
            "<h3 style='margin:24px 0 8px;font-size:15px'>Gesprächsverlauf</h3>"
            "<div style='background:#f6f6f8;border-radius:8px;padding:12px;font-size:13px;"
            f"white-space:pre-wrap;line-height:1.5'>{escape(transcript)}</div>"
        )
    return (
        "<div style='font-family:Arial,sans-serif;font-size:14px;color:#111;max-width:640px'>"
        f"<h2 style='margin:0 0 12px;font-size:18px'>{escape(title)}</h2>"
        f"<table style='border-collapse:collapse'>{rows_html}</table>"
        f"{transcript_html}"
        "<p style='margin-top:24px;color:#888;font-size:12px'>Gesendet vom KI-Agenten auf deinem Portfolio.</p>"
        "</div>"
    )


# ---------------------------------------------------------------------------
# Tools für das Modell
# ---------------------------------------------------------------------------
def record_user_details(email, name="", notes="", transcript=""):
    subject = f"Neuer Kontakt aus dem KI-Chat: {name or email}"
    html_body = _email_layout(
        "Neuer Kontakt aus dem KI-Chat",
        [("Name", name or "nicht angegeben"), ("E-Mail", email), ("Worum geht es", notes)],
        transcript,
    )
    ok = send_email(subject, html_body, reply_to=email)
    return {"recorded": "ok" if ok else "failed"}


def record_unknown_question(question, transcript=""):
    subject = f"Unbeantwortete Frage im KI-Chat: {question[:60]}"
    html_body = _email_layout(
        "Diese Frage konnte der Agent nicht beantworten",
        [("Frage", question), ("Tipp", "Ergänze die Antwort in me/summary.txt.")],
        transcript,
    )
    ok = send_email(subject, html_body)
    return {"recorded": "ok" if ok else "failed"}


record_user_details_json = {
    "name": "record_user_details",
    "description": "Forward the visitor's contact details and request to the real Achraf by email. Use it once per conversation, as soon as the visitor has given an email address and wants to be contacted (job, interview, project, offer, call).",
    "parameters": {
        "type": "object",
        "properties": {
            "email": {
                "type": "string",
                "description": "The email address of this user",
            },
            "name": {
                "type": "string",
                "description": "The user's name, if they provided it",
            },
            "notes": {
                "type": "string",
                "description": "Short summary in German of what the visitor wants (e.g. job offer, project idea, request for a quote, budget, timeline, company) so Achraf can reply without reading the whole chat",
            },
        },
        "required": ["email"],
        "additionalProperties": False,
    },
}

record_unknown_question_json = {
    "name": "record_unknown_question",
    "description": "Always use this tool to record any question that couldn't be answered as you didn't know the answer",
    "parameters": {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question that couldn't be answered",
            },
        },
        "required": ["question"],
        "additionalProperties": False,
    },
}

tools = [
    {"type": "function", "function": record_user_details_json},
    {"type": "function", "function": record_unknown_question_json},
]


class Me:

    def __init__(self):
        self.openai = OpenAI()
        self.name = "Achraf Ayadi"
        reader = PdfReader("me/linkedin.pdf")
        self.linkedin = ""
        for page in reader.pages:
            text = page.extract_text()
            if text:
                self.linkedin += text
        with open("me/summary.txt", "r", encoding="utf-8") as f:
            self.summary = f.read()

    @staticmethod
    def build_transcript(messages):
        """Gesprächsverlauf als Text für die Benachrichtigungs-E-Mail."""
        lines = []
        for m in messages:
            role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
            content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                speaker = "Besucher" if role == "user" else "Agent"
                lines.append(f"{speaker}: {content.strip()}")
        return "\n\n".join(lines)

    def handle_tool_call(self, tool_calls, transcript=""):
        allowed_tools = {
            "record_user_details": record_user_details,
            "record_unknown_question": record_unknown_question,
        }
        results = []
        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            print(f"Tool called: {tool_name}", flush=True)
            tool = allowed_tools.get(tool_name)
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
                result = tool(**arguments, transcript=transcript) if tool else {"error": "unknown tool"}
            except Exception as e:
                print(f"Tool error ({tool_name}): {e}", flush=True)
                result = {"recorded": "failed"}
            results.append(
                {
                    "role": "tool",
                    "content": json.dumps(result),
                    "tool_call_id": tool_call.id,
                }
            )
        return results

    def system_prompt(self):
        system_prompt = f"""You are {self.name}, chatting with visitors on your own portfolio website. \
Most visitors are recruiters or hiring managers; some are potential clients. Answer in the first person, as {self.name} would in a relaxed but professional conversation.

## How to answer
- Answer exactly what was asked, nothing more. Do not volunteer your tech stack, projects or services unless the question is about them.
- Keep it short: usually 1-3 sentences. Only go longer if the visitor asks for details.
- A greeting or small talk ("Hi", "Wie geht's?") gets a short, friendly reply plus one short question back, e.g. "Hallo! Schön, dass Sie da sind. Was möchten Sie über mich wissen?" No self-introduction, no skill list.
- Write like a real person in a chat: plain sentences, no bullet lists or bold text unless the visitor asks for an overview or list.
- Avoid marketing and typical AI phrasing: no "Gerne!", "Großartige Frage", "Ich helfe Unternehmen ...", "maßgeschneidert", "innovativ", "Lassen Sie mich wissen". No emojis.
- When asked about experience, give concrete facts (company, role, period, what you actually did) from the context below instead of general claims.
- Reply in the visitor's language. In German, address them formally with "Sie".

## Facts and honesty
- Only use facts from the summary and LinkedIn profile below. Never invent employers, dates, salaries, prices, availability dates or client names.
- If you don't know something, say so briefly (e.g. "Das kann ich hier leider nicht beantworten, schreiben Sie mir gern direkt.") and record it with your record_unknown_question tool.
- Share contact details only when asked or when the visitor wants to get in touch: email ayadi.achraf2@gmail.com, LinkedIn and GitHub. Do not share your phone number or home address.

## What you can and cannot do
- You are an AI version of Achraf on his website. You CANNOT send emails, write or send offers/quotes, send documents (CV, certificates), book meetings or make commitments on Achraf's behalf.
- Never say or imply that you will do any of these things ("Ich sende Ihnen ...", "Ich bereite ein Angebot vor ...", "Ich melde mich morgen ..."). These are false promises.
- The only action you can take is forwarding the visitor's request to the real Achraf with your record_user_details tool. He then replies personally by email.

## Getting in touch
- Only ask for the visitor's email when they show real interest (a job opening, an interview, a project, an offer or wanting to talk). Ask at most once per conversation, and don't ask again if they declined or ignored it.
- As soon as the visitor has given an email address and wants to be contacted, call record_user_details once. In "notes", summarise in German what they want (role or project, offer request, budget, timeline, company) so Achraf can reply without reading the chat. Do not insist on more details first; if they don't want to share more, forward what you have.
- After the tool returns "ok", confirm honestly, e.g.: "Danke! Ich habe Ihre Anfrage an mich weitergeleitet, ich melde mich persönlich per E-Mail bei Ihnen." Don't give a specific date or time.
- If the tool returns "failed", apologise briefly and ask them to write directly to ayadi.achraf2@gmail.com.
- Never call record_user_details twice for the same email in one conversation.

## Conversation flow
- Don't end every message with a question. Never ask whether the visitor wants to continue or end the chat.
- If the visitor says goodbye or wants to stop, reply with one short friendly sentence.
"""

        system_prompt += f"\n\n## Summary:\n{self.summary}\n\n## LinkedIn Profile:\n{self.linkedin}\n\n"
        system_prompt += f"With this context, chat with the visitor, always staying in character as {self.name}."
        return system_prompt

    def chat(self, message, history):
        messages = (
            [{"role": "system", "content": self.system_prompt()}]
            + history
            + [{"role": "user", "content": message}]
        )
        done = False
        while not done:
            response = self.openai.chat.completions.create(
                model="gpt-5-nano", messages=messages, tools=tools
            )
            if response.choices[0].finish_reason == "tool_calls":
                message = response.choices[0].message
                tool_calls = message.tool_calls
                results = self.handle_tool_call(
                    tool_calls, transcript=self.build_transcript(messages)
                )
                messages.append(message)
                messages.extend(results)
            else:
                done = True
        return response.choices[0].message.content


if __name__ == "__main__":
    me = Me()
    gr.ChatInterface(me.chat, type="messages").launch()
