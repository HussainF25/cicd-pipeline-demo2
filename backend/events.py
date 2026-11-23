"""ASYNC PATH - local queue + background worker.

Today:   publish_event() -> Python queue -> worker thread -> handle_event()
Future:  publish_event() -> Amazon SQS   -> AWS Lambda    -> handle_event()

To move to AWS:
  1. In publish_event(), replace `_queue.put(...)` with
     boto3.client("sqs").send_message(QueueUrl=..., MessageBody=json.dumps(event))
  2. Deploy handle_event() as a Lambda function triggered by that SQS queue.
  3. Replace the database insert with Amazon SES (email) or SNS (SMS).
"""
import queue
import threading
import time

from .database import get_conn

_queue = queue.Queue()


def publish_event(event_type, recipient, message):
    """Called by the backend. Returns immediately - it never waits for sending."""
    _queue.put({"type": event_type, "recipient": recipient, "message": message})


def handle_event(event):
    """Plays the role of the Lambda function: 'sends' the notification."""
    time.sleep(1.0)  # pretend email delivery takes time - shows the work is async
    conn = get_conn()
    conn.execute(
        "INSERT INTO notifications (event_type, recipient, message) VALUES (?, ?, ?)",
        (event["type"], event["recipient"], event["message"]),
    )
    conn.commit()
    conn.close()
    print(f"[worker] sent {event['type']} to {event['recipient']}")


def _worker_loop():
    while True:
        event = _queue.get()
        try:
            handle_event(event)
        except Exception as exc:  # in AWS, failures would be retried, then sent to the DLQ
            print(f"[worker] failed: {exc}")
        finally:
            _queue.task_done()


def start_worker():
    threading.Thread(target=_worker_loop, daemon=True).start()
