import os
from typing import Dict


import requests
from agents import Agent, function_tool


@function_tool
def send_email(subject: str, html_body: str) -> Dict[str, str]:
    """Send an email with the given subject and HTML body"""
    domain = os.environ["MAILGUN_DOMAIN"]
    api_key = os.environ["MAILGUN_API_KEY"]
    base_url = os.environ.get("MAILGUN_BASE_URL", "https://api.mailgun.net")

    response = requests.post(
        f"{base_url}/v3/{domain}/messages",
        auth=("api", api_key),
        data={
            "from": f"Agent <postmaster@{domain}>",
            "to": "Achraf <ayadi.achraf2@gmail.com>",
            "subject": subject,
            "html": html_body,
        },
        timeout=30,
    )
    print("Email response", response.status_code)
    response.raise_for_status()
    return {"status": "success"}


INSTRUCTIONS = """You are able to send a nicely formatted HTML email based on a detailed report.
You will be provided with a detailed report. You should use your tool to send one email, providing the 
report converted into clean, well presented HTML with an appropriate subject line."""

email_agent = Agent(
    name="Email agent",
    instructions=INSTRUCTIONS,
    tools=[send_email],
    model="gpt-5-nano",
)
