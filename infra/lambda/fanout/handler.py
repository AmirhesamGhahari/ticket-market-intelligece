import json
import os

import boto3

ecs = boto3.client("ecs")


def lambda_handler(event, context):
    cluster = os.environ["ECS_CLUSTER_ARN"]
    task_family = os.environ["TASK_DEFINITION_FAMILY"]
    subnets = os.environ["SUBNET_IDS"].split(",")
    sg = os.environ["SECURITY_GROUP_ID"]
    event_configs = json.loads(os.environ["EVENT_CONFIGS"])
    mode = event.get("mode", "initial")

    results = []
    for config_name in event_configs:
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
                        "command": [
                            "from-apify",
                            "--config",
                            config_name,
                            "--mode",
                            mode,
                        ],
                    }
                ]
            },
        )
        task_arns = [t["taskArn"] for t in resp.get("tasks", [])]
        failures = resp.get("failures", [])
        results.append({"config": config_name, "tasks": task_arns, "failures": failures})
        print(f"Launched {config_name}: tasks={task_arns} failures={failures}")

    return {"launched": len(event_configs), "results": results}
