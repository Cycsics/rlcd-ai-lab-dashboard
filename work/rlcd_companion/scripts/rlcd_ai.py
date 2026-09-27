#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import NamedTuple
from typing import Any


DEFAULT_SERVER = "http://127.0.0.1:8787"


class StatusSpec(NamedTuple):
    status: str
    default_title: str


STATUS_ALIASES: dict[str, StatusSpec] = {
    "idle": StatusSpec("idle", "没有任务"),
    "clear": StatusSpec("idle", "没有任务"),
    "reset": StatusSpec("idle", "没有任务"),
    "coding": StatusSpec("coding", "正在执行"),
    "busy": StatusSpec("coding", "正在执行"),
    "start": StatusSpec("coding", "正在执行"),
    "done": StatusSpec("done", "工作已完成"),
    "finish": StatusSpec("done", "工作已完成"),
    "finished": StatusSpec("done", "工作已完成"),
    "needs_confirm": StatusSpec("needs_confirm", "等待确认"),
    "confirm": StatusSpec("needs_confirm", "等待确认"),
    "need": StatusSpec("needs_confirm", "等待确认"),
    "interrupted": StatusSpec("interrupted", "任务已中断"),
    "interrupt": StatusSpec("interrupted", "任务已中断"),
    "failed": StatusSpec("interrupted", "任务已中断"),
    "fail": StatusSpec("interrupted", "任务已中断"),
    "error": StatusSpec("interrupted", "任务已中断"),
}


def normalize_server_url(value: str) -> str:
    return value.rstrip("/")


def build_ai_payload(action: str, title_parts: list[str]) -> dict[str, str]:
    key = action.strip().lower().replace("-", "_")
    if key not in STATUS_ALIASES:
        known = ", ".join(sorted(STATUS_ALIASES))
        raise ValueError(f"未知状态：{action}。可用状态：{known}")
    spec = STATUS_ALIASES[key]
    title = " ".join(part for part in title_parts if part).strip() or spec.default_title
    return {"status": spec.status, "title": title}


def request_json(method: str, url: str, payload: dict[str, Any] | None, timeout: float) -> dict[str, Any]:
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"请求失败：{url}；{exc}") from exc

    if not data:
        return {}
    try:
        return json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"服务返回的不是 JSON：{data[:120]!r}") from exc


def print_result(data: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, ensure_ascii=False, sort_keys=True), flush=True)
        return

    if "ai_status" in data:
        alert = data.get("alert") or "无"
        print(f"状态：{data.get('ai_status')}｜标题：{data.get('ai_title')}｜提醒：{alert}", flush=True)
    elif "ack" in data:
        print(f"已确认：{data.get('ack') or '当前无提醒'}", flush=True)
    elif "status" in data:
        print(f"已更新：{data.get('status')}｜{data.get('title')}", flush=True)
    else:
        print(json.dumps(data, ensure_ascii=False, sort_keys=True), flush=True)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rlcd-ai",
        description="更新 RLCD 桌面小伙伴的 AI Coding 状态。",
    )
    parser.add_argument(
        "--server",
        default=os.environ.get("RLCD_SERVER_URL", DEFAULT_SERVER),
        help=f"RLCD 服务地址，默认 {DEFAULT_SERVER}；也可用 RLCD_SERVER_URL。",
    )
    parser.add_argument("--timeout", type=float, default=3.0, help="HTTP 超时时间，默认 3 秒。")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON。")
    parser.add_argument(
        "command",
        help="状态命令：coding、done、needs_confirm、interrupted、idle、ack、state。",
    )
    parser.add_argument("title", nargs="*", help="显示在 AI Coding 区的标题。")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    server = normalize_server_url(args.server)
    command = args.command.strip().lower().replace("-", "_")

    if command == "state":
        return request_json("GET", f"{server}/state", None, args.timeout)
    if command == "ack":
        return request_json("POST", f"{server}/ack", None, args.timeout)

    payload = build_ai_payload(command, args.title)
    return request_json("POST", f"{server}/ai", payload, args.timeout)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = run(args)
    except Exception as exc:
        print(f"rlcd-ai 失败：{exc}", file=sys.stderr)
        return 1
    print_result(result, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
