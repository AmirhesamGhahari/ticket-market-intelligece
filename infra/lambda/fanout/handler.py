import json
import os

import boto3

ecs = boto3.client("ecs")


def lambda_handler(event, context):
    cluster = os.environ["ECS_CLUSTER_ARN"]
    task_family = os.environ["TASK_DEFINITION_FAMILY"]
    subnets = os.environ["SUBNET_IDS"].split(",")
    sg = os.environ["SECURITY_GROUP_ID"]
    facebook_configs = json.loads(os.environ["FACEBOOK_EVENT_CONFIGS"])
    seatgeek_configs = json.loads(os.environ["SEATGEEK_EVENT_CONFIGS"])

    # Optional payload overrides — omit all to keep the default scheduled fan-out behaviour.
    # config_name: run only this one config instead of the source's full config list
    # command: "classify" | "from-apify" | "from-seatgeek"
    #          omit (or null) to run ALL sources, each against its own config list
    # mode: "initial" | "periodic" (default "periodic")
    # stage: "scrape" | "classify" | "all" (default "all", only used by from-apify)
    target_config = event.get("config_name")
    command = event.get("command")  # None = scheduled run → triggers all sources
    mode = event.get("mode", "periodic")
    stage = event.get("stage", "all")

    def _run_cmd(cmd):
        # Dockerfile has no ENTRYPOINT, so the full command including the
        # CLI entrypoint (run-facebook / run-seatgeek) goes in the override.
        resp = ecs.run_task(
            cluster=cluster,
            taskDefinition=task_family,
            launchType="FARGATE",
            networkConfiguration={
                "awsvpcConfiguration": {
                    "subnets": subnets,
                    "securityGroups": [sg],
                    "assignPublicIp": "ENABLED",
                }
            },
            overrides={
                "containerOverrides": [{"name": "pipeline", "command": cmd}]
            },
        )
        return resp

    results = []

    def _launch(config_name, cmd):
        resp = _run_cmd(cmd)
        task_arns = [t["taskArn"] for t in resp.get("tasks", [])]
        failures = resp.get("failures", [])
        results.append({"config": config_name, "command": cmd, "tasks": task_arns, "failures": failures})
        print(f"Launched {config_name} ({' '.join(cmd)}): tasks={task_arns} failures={failures}")

    if command == "classify":
        for config_name in [target_config] if target_config else facebook_configs:
            _launch(config_name, ["run-facebook", "classify", "--config", config_name])
    elif command == "from-seatgeek":
        for config_name in [target_config] if target_config else seatgeek_configs:
            _launch(config_name, ["run-seatgeek", "from-api", "--config", config_name, "--mode", mode])
    elif command == "from-apify":
        for config_name in [target_config] if target_config else facebook_configs:
            _launch(config_name, ["run-facebook", "from-apify", "--config", config_name, "--mode", mode, "--stage", stage])
    else:
        # Scheduled/manual full run: each source runs against its own config list
        for config_name in [target_config] if target_config else facebook_configs:
            _launch(config_name, ["run-facebook", "from-apify", "--config", config_name, "--mode", mode, "--stage", stage])
        for config_name in [target_config] if target_config else seatgeek_configs:
            _launch(config_name, ["run-seatgeek", "from-api", "--config", config_name, "--mode", mode])

    return {"launched": len(results), "results": results}
