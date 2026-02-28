import os
import time
import requests
import logging
import smtplib
import json
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2 import sql
from qdrant_client import QdrantClient

logging.basicConfig(level=logging.INFO)

OPENOBSERVE_URL = os.environ.get("OPENOBSERVE_URL", "http://openobserve:5080")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
TOOL = os.environ.get("Tool", "DEEPSEEK").upper()
API_KEY = os.environ.get("API_KEY", "")

SLACK_WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")
EMAIL_TO = os.environ.get("EMAIL_TO")
SMTP_SERVER = os.environ.get("SMTP_SERVER")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")
# PostgreSQL configuration
PG_HOST = os.environ.get("POSTGRES_HOST", "postgres")
PG_PORT = os.environ.get("POSTGRES_PORT", "5432")
PG_USER = os.environ.get("POSTGRES_USER", "logprobe")
PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "probe_pass")
PG_DB = os.environ.get("POSTGRES_DB", "logprobe_results")
# PostgreSQL configuration
PG_HOST = os.environ.get("POSTGRES_HOST", "postgres")
PG_PORT = os.environ.get("POSTGRES_PORT", "5432")
PG_USER = os.environ.get("POSTGRES_USER", "logprobe")
PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "probe_pass")
PG_DB = os.environ.get("POSTGRES_DB", "logprobe_results")

#qdrant client
qdrant = QdrantClient(url=QDRANT_URL)


# ---------- PostgreSQL Helpers ----------
def get_db_connection():
    """Establish a connection to PostgreSQL."""
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        user=PG_USER,
        password=PG_PASSWORD,
        database=PG_DB,
    )


def init_db():
    """Initialize database: check all service connections and create schema if needed."""
    logging.info("initializing probe...")
    
    # 1. Check OpenObserve connectivity
    try:
        resp = requests.get(f"{OPENOBSERVE_URL}/api/health", timeout=5)
        logging.info("✓ OpenObserve available")
    except Exception as e:
        logging.warning("✗ OpenObserve unreachable: %s", e)
    
    # 2. Check Qdrant connectivity
    try:
        resp = requests.get(f"{QDRANT_URL}/health", timeout=5)
        logging.info("✓ Qdrant available")
    except Exception as e:
        logging.warning("✗ Qdrant unreachable: %s", e)
    
    # 3. Check PostgreSQL connectivity and create schema
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create the probe_analyses table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS probe_analyses (
                id SERIAL PRIMARY KEY,
                error_id VARCHAR(255) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                problem_description TEXT,
                root_cause_summary TEXT,
                suggested_solution TEXT,
                confidence_score FLOAT,
                raw_response JSONB
            );
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        logging.info("✓ PostgreSQL available and schema initialized")
    except Exception as e:
        logging.error("✗ PostgreSQL error: %s", e)
        raise


def store_analysis(error_id, ai_response):
    """Parse AI response and store it in PostgreSQL."""
    try:
        # Try to parse the JSON response from AI
        if isinstance(ai_response, str):
            # Extract JSON from the response (in case there's extra text)
            import re
            json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if json_match:
                response_data = json.loads(json_match.group())
            else:
                logging.warning("Could not find JSON in AI response")
                response_data = {"raw_response": ai_response}
        else:
            response_data = ai_response
        
        problem_desc = response_data.get("problem_description", "")
        root_cause = response_data.get("root_cause_summary", "")
        solution = response_data.get("suggested_solution", "")
        confidence = response_data.get("confidence_score", 0.0)
        
        # Store in database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO probe_analyses (
                error_id, problem_description, root_cause_summary,
                suggested_solution, confidence_score, raw_response
            ) VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            error_id,
            problem_desc,
            root_cause,
            solution,
            confidence,
            json.dumps(response_data),
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        logging.info("stored analysis for error %s", error_id)
    except Exception as e:
        logging.error("failed to store analysis: %s", e)


# OpenObserve interaction
def fetch_errors():
    """Query OpenObserve for recent error events from the last 2 minutes."""
    try:
        # calculate time range: last 2 minutes
        now = datetime.now(timezone.utc)
        two_mins_ago = now - timedelta(minutes=2)
        time_filter = two_mins_ago.timestamp()  # unix timestamp in seconds
        
        # adjust params based on your OpenObserve API version
        # common param names: start_time, end_time, time_start, time_end, timestamp_gt, etc.
        resp = requests.get(
            f"{OPENOBSERVE_URL}/api/logs",
            params={
                "level": "error",
                "limit": 20,
                "start_time": int(time_filter * 1_000_000),  # convert to microseconds (OpenObserve format)
            },
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
    except Exception as e:
        logging.error("failed to fetch errors: %s", e)
        return []


def fetch_surrounding_logs(log_id, before=5, after=5):
    """Retrieve logs around a specific log entry. Placeholder implementation."""
    # OpenObserve query parameters may differ; adjust according to your installation
    try:
        resp = requests.get(
            f"{OPENOBSERVE_URL}/api/logs/{log_id}/context",
            params={"before": before, "after": after},
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logging.warning("couldn't fetch surrounding logs for %s: %s", log_id, e)
        return {}


# Qdrant interaction
def query_qdrant(vector):
    """Look up related information in Qdrant using a vector representation or text.
    This function uses a simple text search; adapt it to your index schema."""
    try:
        result = qdrant.search(
            collection_name="default",
            query_vector=vector,
            limit=5,
        )
        return result
    except Exception as e:
        logging.error("qdrant query failed: %s", e)
        return []


# AI tool interaction
def ask_ai(prompt_text):
    logging.info("sending prompt to tool %s", TOOL)
    if TOOL == "OPENAI":
        import openai
        openai.api_key = API_KEY
        resp = openai.ChatCompletion.create(
            model="gpt-4", messages=[{"role": "user", "content": prompt_text}]
        )
        return resp.choices[0].message.content
    elif TOOL == "ANTHROPIC":
        import anthropic
        client = anthropic.Client(api_key=API_KEY)
        resp = client.completions.create(model="claude-3", prompt=prompt_text)
        return resp.completion
    elif TOOL == "DEEPSEEK":
        # sample HTTP call for Deepseek; adjust with real API spec
        resp = requests.post(
            "https://api.deepseek.ai/v1/query",
            json={"input": prompt_text},
            headers={"Authorization": f"Bearer {API_KEY}"},
        )
        resp.raise_for_status()
        return resp.json().get("result", "")
    else:
        raise ValueError(f"unknown tool {TOOL}")


# notification
def notify_slack(message):
    if not SLACK_WEBHOOK:
        return
    requests.post(SLACK_WEBHOOK, json={"text": message})


def notify_discord(message):
    if not DISCORD_WEBHOOK:
        return
    requests.post(DISCORD_WEBHOOK, json={"content": message})


def notify_email(subject, body):
    if not (EMAIL_TO and SMTP_SERVER):
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = SMTP_USER or "logprobe@example.com"
    msg["To"] = EMAIL_TO

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        if SMTP_USER and SMTP_PASS:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(msg["From"], [EMAIL_TO], msg.as_string())


def broadcast(message, subject="Log probe alert"):
    notify_slack(message)
    notify_discord(message)
    notify_email(subject, message)


# ---------- main loop ----------
processed = set()


def build_prompt(error, context_logs, qdrant_info):
    # construct a LogSightPrompt-like instruction with sections described by the user
    # error is assumed to be a dict-like object; context_logs and qdrant_info may be lists
    instruction = (
        "[SYSTEM_INSTRUCTION]\n"
        "You are LogSight RCA Agent. Analyze the provided operational data and history to find the root cause (RC) and provide a fix.\n\n"
        "[CONTEXT]\n"
        f"Error: {error.get('message', error)}\n"
        f"Log_ID: {error.get('id', error.get('_id', 'unknown'))}\n\n"
        "[RECENT_LOG_SEQUENCE]\n"
        "# recent surrounding logs (time offsets approximate)\n"
        f"{context_logs}\n\n"
        "[RETRIEVED_KNOWLEDGE]\n"
        f"{qdrant_info}\n\n"
        "[OUTPUT_REQUEST]\n"
        "Provide the root cause and a solution in the following JSON format ONLY:\n"
        "{ \"problem_description\": \"...\", \"root_cause_summary\": \"...\", \"suggested_solution\": \"...\", \"confidence_score\": 0.95 }"
    )
    return instruction


def main():
    # initialize database and verify service connectivity
    init_db()
    
    logging.info("starting log probe")

    while True:
        errors = fetch_errors()

        for err in errors:

            err_id = err.get("id") or err.get("_id")

            if err_id in processed:
                continue

            processed.add(err_id)

            context = fetch_surrounding_logs(err_id)
            
            # convert error text to vector
            vector = err.get("message", "")
            qinfo = query_qdrant(vector)

            prompt = build_prompt(err, context, qinfo)
            answer = ask_ai(prompt)
            
            # store analysis result in PostgreSQL
            store_analysis(err_id, answer)
            
            # broadcast to notification channels
            broadcast(answer)
        
        time.sleep(5)


if __name__ == "__main__":
    main()
