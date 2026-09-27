#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import rlcd_ai


DEFAULT_TITLES = {
    "start": "Codex 正在工作",
    "done": "Codex 工作完成",
    "confirm": "Codex 需要你确认",
    "fail": "Codex 工作中断",
    "idle": "没有任务",
}

ACTION_TO_AI = {
    "start": "coding",
    "done": "done",
    "confirm": "needs_confirm",
    "fail": "needs_confirm",
    "idle": "idle",
}


def title_from_parts(parts: list[str], fallback: str) -> str:
    return " ".join(part for part in parts if part).strip() or fallback


def strip_separator(command: list[str]) -> list[str]:
    if command and command[0] == "--":
        return command[1:]
    return command


def command_title(title: str, command: list[str]) -> str:
    if title:
        return title
    if command:
        return f"运行 {Path(command[0]).name}"
    return "运行命令"


def send_ai(command: str, title: str, server: str, timeout: float) -> dict[str, Any]:
    args = argparse.Namespace(
        command=command,
        title=[title],
        server=server,
        timeout=timeout,
        json=True,
    )
    return rlcd_ai.run(args)


def default_project() -> str:
    return os.environ.get("RLCD_PROJECT") or os.environ.get("CODEX_PROJECT_NAME") or Path.cwd().name


def default_conversation_title() -> str:
    for key in (
        "RLCD_CONVERSATION_TITLE",
        "CODEX_THREAD_TITLE",
        "CODEX_CONVERSATION_TITLE",
    ):
        value = os.environ.get(key)
        if value:
            return value
    return ""


def default_session_id() -> str:
    for key in (
        "RLCD_SESSION_ID",
        "CODEX_THREAD_ID",
        "CODEX_SESSION_ID",
        "CODEX_TURN_ID",
        "CLAUDE_SESSION_ID",
    ):
        value = os.environ.get(key)
        if value:
            return value
    seed = f"{Path.cwd()}:{os.getppid()}"
    return f"local:{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}"


def codex_status_payload(args: argparse.Namespace, status: str, title: str) -> dict[str, str]:
    return {
        "status": status,
        "title": title,
        "session_id": args.session_id or default_session_id(),
        "project": args.project or default_project(),
        "conversation_title": args.conversation_title or default_conversation_title(),
        "source": args.source or "rlcd-task",
        "cwd": str(Path.cwd()),
    }


def send_codex_status(
    status: str,
    title: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    server = rlcd_ai.normalize_server_url(args.server)
    return rlcd_ai.request_json(
        "POST",
        f"{server}/codex/status",
        codex_status_payload(args, status, title),
        args.timeout,
    )


def notify_or_warn(command: str, title: str, args: argparse.Namespace) -> None:
    try:
        result = send_codex_status(command, title, args)
    except Exception as exc:
        if args.strict_notify:
            raise
        print(f"RLCD 通知失败：{exc}", file=sys.stderr)
        return
    rlcd_ai.print_result(result, as_json=False)


def run_wrapped_command(args: argparse.Namespace) -> int:
    command = strip_separator(args.command)
    if not command:
        print("rlcd-run 失败：缺少要执行的命令。格式：rlcd-run 任务名 -- 命令 参数", file=sys.stderr)
        return 2

    title = command_title(args.title, command)
    notify_or_warn("coding", f"正在执行：{title}", args)

    completed = subprocess.run(command)
    if completed.returncode == 0:
        notify_or_warn("done", f"已完成：{title}", args)
    else:
        notify_or_warn(
            "needs_confirm",
            f"失败：{title}（退出码 {completed.returncode}）",
            args,
        )
    return completed.returncode


def run_lifecycle_action(args: argparse.Namespace) -> int:
    if args.action == "state":
        result = rlcd_ai.run(
            argparse.Namespace(
                command="state",
                title=[],
                server=args.server,
                timeout=args.timeout,
                json=args.json,
            )
        )
        rlcd_ai.print_result(result, as_json=args.json)
        return 0

    if args.action == "ack":
        result = rlcd_ai.run(
            argparse.Namespace(
                command="ack",
                title=[],
                server=args.server,
                timeout=args.timeout,
                json=args.json,
            )
        )
        rlcd_ai.print_result(result, as_json=args.json)
        return 0

    ai_command = ACTION_TO_AI[args.action]
    title = title_from_parts(args.title, DEFAULT_TITLES[args.action])
    result = send_codex_status(ai_command, title, args)
    rlcd_ai.print_result(result, as_json=args.json)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    argv = normalize_global_options(argv)
    parser = argparse.ArgumentParser(
        prog="rlcd-task",
        description="Codex/脚本任务生命周期上报到 RLCD 桌面小伙伴。",
    )
    parser.add_argument("--server", default=rlcd_ai.DEFAULT_SERVER, help="RLCD 服务地址。")
    parser.add_argument("--timeout", type=float, default=3.0, help="HTTP 超时时间，默认 3 秒。")
    parser.add_argument("--json", action="store_true", help="输出原始 JSON。")
    parser.add_argument(
        "--strict-notify",
        action="store_true",
        help="通知失败时直接失败；默认只警告，不阻断被包裹命令。",
    )
    parser.add_argument("--session-id", default="", help="Codex 会话 ID；默认自动从环境变量或当前 shell 生成。")
    parser.add_argument("--project", default="", help="显示用项目名；默认使用当前目录名。")
    parser.add_argument("--conversation-title", default="", help="显示用对话标题；默认读取 RLCD_CONVERSATION_TITLE。")
    parser.add_argument("--source", default="rlcd-task", help="状态来源，默认 rlcd-task。")

    subparsers = parser.add_subparsers(dest="action", required=True)

    for action in ("start", "done", "confirm", "fail", "idle"):
        sub = subparsers.add_parser(action)
        sub.add_argument("title", nargs="*")

    subparsers.add_parser("ack")
    subparsers.add_parser("state")

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("title", help="任务标题。")
    run_parser.add_argument("command", nargs=argparse.REMAINDER, help="要执行的命令，建议用 -- 分隔。")

    return parser.parse_args(argv)


def normalize_global_options(argv: list[str]) -> list[str]:
    """Allow global options before or after the subcommand.

    argparse normally requires root parser options before the subcommand. For
    this CLI, `rlcd-task state --json` is the shape users naturally type. Stop
    rewriting after `--` so wrapped command flags stay untouched.
    """
    options_with_values = {"--server", "--timeout"}
    options_with_values.update({"--session-id", "--project", "--conversation-title", "--source"})
    flag_options = {"--json", "--strict-notify"}
    global_options: list[str] = []
    rest: list[str] = []
    index = 0

    while index < len(argv):
        token = argv[index]
        if token == "--":
            rest.extend(argv[index:])
            break
        if token in flag_options:
            global_options.append(token)
            index += 1
            continue
        if token in options_with_values:
            if index + 1 >= len(argv):
                rest.append(token)
                index += 1
                continue
            global_options.extend([token, argv[index + 1]])
            index += 2
            continue
        rest.append(token)
        index += 1

    return global_options + rest


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.action == "run":
            return run_wrapped_command(args)
        return run_lifecycle_action(args)
    except Exception as exc:
        print(f"rlcd-task 失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
