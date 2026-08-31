import json
import os

import boto3

ecs = boto3.client("ecs")


def lambda_handler(event, context):
    cluster = os.environ["ECS_CLUSTER_ARN"]
    task_family = os.environ["TASK_DEFINITION_FAMILY"]
    subnets = os.environ["SUBNET_IDS"].split(",")
    sg = os.environ["SECURITY_GROUP_ID"]
    all_configs = json.loads(os.environ["EVENT_CONFIGS"])

    # Optional payload overrides — omit all to keep the default scheduled fan-out behaviour.
    # config_name: run only this one config instead of all configs in EVENT_CONFIGS
    # command: "classify" | "from-apify" (default "from-apify")
    # mode: "initial" | "periodic" (default "periodic", only used by from-apify)
    # stage: "scrape" | "classify" | "all" (default "all", only used by from-apify)
    target_config = event.get("config_name")
    command = event.get("command", "from-apify")
    mode = event.get("mode", "periodic")
    stage = event.get("stage", "all")

    configs_to_run = [target_config] if target_config else all_configs

    results = []
    for config_name in configs_to_run:
        if command == "classify":
            cmd = ["classify", "--config", config_name]
        else:
            cmd = ["from-apify", "--config", config_name, "--mode", mode, "--stage", stage]

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
                "containerOverrides": [
                    {
                        "name": "pipeline",
                        "command": cmd,
                    }
                ]
            },
        )
        task_arns = [t["taskArn"] for t in resp.get("tasks", [])]
        failures = resp.get("failures", [])
        results.append({"config": config_name, "command": cmd, "tasks": task_arns, "failures": failures})
        print(f"Launched {config_name} ({' '.join(cmd)}): tasks={task_arns} failures={failures}")

    return {"launched": len(configs_to_run), "results": results}
