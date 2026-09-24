"""Step Functions task-token callback.

When Step Functions launches an ECS task with the waitForTaskToken pattern, it
injects TASK_TOKEN as an environment variable. The task must call report_success()
or report_failure() before it exits so Step Functions can proceed.

If TASK_TOKEN is not set (local / dev run), both functions are no-ops — no change
to local behaviour.
"""
from __future__ import annotations

import json
import os

import boto3


def report_success(stats: dict) -> None:
    token = os.environ.get("TASK_TOKEN")
    if not token:
        return
    boto3.client("stepfunctions").send_task_success(
        taskToken=token,
        output=json.dumps(stats),
    )


def report_failure(error: str, cause: str) -> None:
    token = os.environ.get("TASK_TOKEN")
    if not token:
        return
    boto3.client("stepfunctions").send_task_failure(
        taskToken=token,
        error=error[:256],
        cause=cause[:32768],
    )
