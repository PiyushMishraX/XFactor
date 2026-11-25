"""Drive the Red Sea demonstration scenario through the real API.

Run from the ``backend`` directory (or inside the backend container):

    ..\\..\\.venv\\Scripts\\python.exe -m scripts.run_demo_scenario

The script only prints what the API actually recorded. It does not synthesise
agent activity, timings or execution results. The workflow pauses at the human
gate unless a decision is requested with ``--approve`` / ``--reject`` and an
approver token is supplied.

Examples::

    python -m scripts.run_demo_scenario
    python -m scripts.run_demo_scenario --approve --token "$APPROVER_TOKEN"
    python -m scripts.run_demo_scenario --reject --token "$APPROVER_TOKEN" \\
        --comment "Inventory cover is not sufficient for a High-severity reroute."
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

DEFAULT_SCENARIO = Path(__file__).resolve().parents[1] / "demo" / "mumbai_rotterdam_scenario.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8000/api"
TIMEOUT_SECONDS = 300.0


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    token: Optional[str] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = client.request(method, path, headers=headers, json=json_body)
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        raise SystemExit(f"{method} {path} failed ({response.status_code}): {detail}")
    return response.json()


def _print_run_summary(payload: Dict[str, Any], values: Dict[str, Any]) -> None:
    print(f"Thread            : {payload.get('thread_id')}")
    print(f"Status            : {payload.get('status')}")
    print(f"Awaiting approval : {payload.get('awaiting_approval')}")

    decisions = payload.get("decision_log") or []
    if decisions:
        print("\nSupervisor decisions")
        for decision in decisions:
            print(
                f"  - step {decision.get('step')}: {decision.get('action')}"
                f" — {decision.get('reason', '')}"
            )

    executions = payload.get("agent_executions") or []
    if executions:
        print("\nAgent executions (recorded)")
        for execution in executions:
            print(
                f"  - {execution.get('agent')}: {execution.get('status')}"
                f" ({len(execution.get('tool_calls') or [])} tool calls)"
            )

    plan = values.get("scenario_plan") or {}
    recommendation = payload.get("recommendation") or {}
    scenarios = plan.get("scenarios") or []
    if scenarios:
        print(f"\nScenarios ({len(scenarios)})")
        for scenario in scenarios:
            print(
                f"  - {scenario.get('scenario_id')}: {scenario.get('name')} "
                f"[{scenario.get('carrier')} / {scenario.get('transport_mode')}] "
                f"{scenario.get('total_days')} days, "
                f"${scenario.get('total_cost_usd'):,.0f}, risk {scenario.get('risk_score')}"
            )
        print(f"Recommended       : {recommendation.get('recommended_scenario_id')}")

    screening = values.get("scenario_screening") or {}
    if screening:
        evaluations = screening.get("evaluations") or []
        print(
            "Screening         : "
            f"{screening.get('scenario_count', 0)} scenarios, "
            f"{len(evaluations)} evaluated, "
            f"all rejected: {screening.get('all_rejected')}"
        )

    inventory = values.get("rebalancing") or {}
    if inventory:
        print(
            "Inventory cover   : "
            f"{inventory.get('total_transferred_units', 0)} units transferred, "
            f"shortage after {inventory.get('shortage_after')}, "
            f"target {inventory.get('target_plant')}"
        )

    approval_request = payload.get("approval_request")
    if approval_request:
        print("\nApproval request")
        print(f"  - proposal   : {payload.get('proposal_version')}")
        print(f"  - level      : {approval_request.get('approval_level', '')}")
        print(f"  - verdict    : {approval_request.get('verdict', '')}")
        for reason in approval_request.get("reasons") or []:
            print(f"  - reason     : {reason}")


def _print_execution(report: Dict[str, Any]) -> None:
    print("\nExecution report")
    print(f"  - execution : {report.get('execution_id')}")
    print(f"  - status    : {report.get('status')}")
    for action in report.get("actions") or []:
        label = "[SIMULATED]" if action.get("is_mock") else "[LIVE]"
        print(
            f"  - {label} {action.get('action_type')}: {action.get('status')}"
            f" — {action.get('message', '')}"
        )


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the X FACTOR Red Sea demo scenario.")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("XFACTOR_API_BASE_URL", DEFAULT_BASE_URL),
        help=f"API base URL (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument("--scenario", default=str(DEFAULT_SCENARIO), help="Scenario JSON path.")
    parser.add_argument("--thread-id", default=None, help="Override the scenario thread id.")
    parser.add_argument(
        "--action",
        choices=["approve", "reject"],
        default=None,
        help="Submit a human decision after the workflow pauses.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("APPROVER_TOKEN"),
        help="Approver bearer token (or set APPROVER_TOKEN).",
    )
    parser.add_argument("--comment", default="Demo walkthrough decision.")
    args = parser.parse_args(argv)

    if args.action and not args.token:
        parser.error("--action requires --token or APPROVER_TOKEN")

    body = json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    if args.thread_id:
        body["thread_id"] = args.thread_id
    thread_id = body["thread_id"]

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=TIMEOUT_SECONDS) as client:
        print(f"API               : {args.base_url}")
        print(f"Submitting scenario for thread {thread_id} ...\n")
        payload = _request(client, "POST", "/orchestration/workflows", json_body=body)
        state = _request(client, "GET", f"/orchestration/workflows/{thread_id}/state")
        _print_run_summary(payload, state.get("values") or {})

        if not args.action:
            if payload.get("awaiting_approval"):
                print(
                    "\nThe workflow is paused at the human gate. Re-run with "
                    "--action approve|reject --token <token> to decide."
                )
            return 0

        if not payload.get("awaiting_approval"):
            print(f"\nNothing to decide: workflow status is {payload.get('status')!r}.")
            return 0
        proposal_version = payload.get("proposal_version")
        if not proposal_version:
            raise SystemExit("The API did not return a proposal version; cannot decide.")

        decision = _request(
            client,
            "POST",
            f"/approvals/{thread_id}/decision",
            token=args.token,
            json_body={
                "action": args.action,
                "comment": args.comment,
                "proposal_version": proposal_version,
            },
        )
        print("\nDecision")
        record = decision.get("decision") or {}
        print(f"  - action    : {decision.get('action')}")
        print(f"  - approver  : {record.get('approver_id')} ({record.get('approver_role')})")
        print(f"  - status    : {decision.get('workflow_status')}")

        if args.action == "approve":
            report = decision.get("execution")
            if report is None:
                report = _request(
                    client, "GET", f"/approvals/{thread_id}/execution", token=args.token
                )
            _print_execution(report)
        else:
            print("\nRejected actions are not executed; no execution report exists.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
