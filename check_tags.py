#!/usr/bin/env python3
"""Check Cloudflare Wallet tag availability with rate limiting and resume support."""

from __future__ import annotations

import argparse
import http.client
import itertools
import json
import ssl
import string
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode


API_HOST = "cloudflare.pay"
API_PATH = "/api/check"
CHARACTERS = string.digits + string.ascii_lowercase


class RequestFailure(Exception):
    """A network failure after reconnect attempts are exhausted."""


class HTTPStatusFailure(RequestFailure):
    def __init__(self, status: int, reason: str, headers: object, body: bytes = b"") -> None:
        super().__init__(f"HTTP {status} {reason}".strip())
        self.status = status
        self.headers = headers
        self.body = body


EXPECTED_REQUEST_ERRORS = (RequestFailure, TimeoutError, ValueError, json.JSONDecodeError)
_CONNECTION_STATE = threading.local()


class RequestRateLimiter:
    """Space request starts across worker threads."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._next_start = 0.0

    def wait(self) -> None:
        if self.interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self._next_start - now)
            self._next_start = max(now, self._next_start) + self.interval
        if wait_seconds:
            time.sleep(wait_seconds)


def iter_tags(length: int, category: str) -> Iterable[str]:
    for parts in itertools.product(CHARACTERS, repeat=length):
        tag = "".join(parts)
        if category == "numeric" and not tag.isdigit():
            continue
        if category == "alpha" and not tag.isalpha():
            continue
        if category == "mixed" and (tag.isdigit() or tag.isalpha()):
            continue
        yield tag


def candidate_count(length: int, category: str) -> int:
    if category == "numeric":
        return 10**length
    if category == "alpha":
        return 26**length
    if category == "mixed":
        return 36**length - 10**length - 26**length
    return 36**length


def iter_batches(tags: Iterable[str], size: int) -> Iterable[list[str]]:
    iterator = iter(tags)
    while batch := list(itertools.islice(iterator, size)):
        yield batch


def read_input_tags(path: Path) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            tag = line.strip()
            if not tag:
                continue
            key = tag.casefold()
            if key in seen:
                continue
            seen.add(key)
            tags.append(tag)
    return tags


def parse_response(raw: bytes, requested_tag: str) -> tuple[bool, str, str | None]:
    payload = json.loads(raw.decode("utf-8"))
    available = payload.get("available")
    if not isinstance(available, bool):
        raise ValueError("response does not contain a boolean 'available' field")

    normalized = payload.get("normalized", requested_tag)
    if not isinstance(normalized, str):
        normalized = requested_tag
    code = payload.get("code")
    return available, normalized, code if isinstance(code, str) else None


def parse_rejected_tag(error: HTTPStatusFailure, requested_tag: str) -> tuple[bool, str, str]:
    normalized = requested_tag
    code = f"HTTP_{error.status}"
    try:
        payload = json.loads(error.body.decode("utf-8"))
        if isinstance(payload.get("normalized"), str):
            normalized = payload["normalized"]
        if isinstance(payload.get("code"), str):
            code = payload["code"]
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
        pass
    return False, normalized, code


def retry_delay(error: HTTPStatusFailure, attempt: int) -> float:
    retry_after = error.headers.get("Retry-After") if error.headers else None
    if retry_after:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass
    return min(2**attempt, 60)


def close_thread_connection() -> None:
    connection = getattr(_CONNECTION_STATE, "connection", None)
    if connection is not None:
        try:
            connection.close()
        finally:
            _CONNECTION_STATE.connection = None
            _CONNECTION_STATE.timeout = None


def get_thread_connection(timeout: float) -> http.client.HTTPSConnection:
    connection = getattr(_CONNECTION_STATE, "connection", None)
    connection_timeout = getattr(_CONNECTION_STATE, "timeout", None)
    if connection is None or connection_timeout != timeout:
        close_thread_connection()
        connection = http.client.HTTPSConnection(API_HOST, timeout=timeout)
        _CONNECTION_STATE.connection = connection
        _CONNECTION_STATE.timeout = timeout
    return connection


def request_tag(tag: str, timeout: float) -> bytes:
    path = f"{API_PATH}?{urlencode({'tag': tag})}"
    headers = {
        "Accept": "application/json",
        "Connection": "keep-alive",
        "User-Agent": "wallet-tag-checker/1.0",
    }
    last_error: BaseException | None = None

    # A server may close an idle keep-alive socket without notice. Reconnect
    # once immediately before treating it as a request failure.
    for reconnect_attempt in range(2):
        connection = get_thread_connection(timeout)
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            raw = response.read()
            status = response.status
            reason = response.reason or ""
            response_headers = response.headers
            if response.will_close or response.getheader("Connection", "").lower() == "close":
                close_thread_connection()
            if status >= 400:
                raise HTTPStatusFailure(status, reason, response_headers, raw)
            return raw
        except HTTPStatusFailure:
            raise
        except (http.client.HTTPException, OSError, ssl.SSLError) as error:
            last_error = error
            close_thread_connection()
            if reconnect_attempt == 0:
                continue

    raise RequestFailure(str(last_error) if last_error else "unknown connection failure") from last_error


def check_tag(tag: str, timeout: float, retries: int) -> tuple[bool, str, str | None]:
    for attempt in range(retries + 1):
        try:
            return parse_response(request_tag(tag, timeout), tag)
        except HTTPStatusFailure as error:
            if error.status == 400:
                return parse_rejected_tag(error, tag)
            if error.status != 429 and not 500 <= error.status < 600:
                raise
            if attempt == retries:
                raise
            wait_seconds = retry_delay(error, attempt)
            print(
                f"Temporary HTTP {error.status} for @{tag}; retrying in {wait_seconds:g}s...",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(wait_seconds)
        except (RequestFailure, TimeoutError) as error:
            if attempt == retries:
                raise
            wait_seconds = min(2**attempt, 60)
            print(
                f"Request failed for @{tag} ({error}); retrying in {wait_seconds:g}s...",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(wait_seconds)

    raise RuntimeError("unreachable")


def check_tag_safe(
    tag: str,
    timeout: float,
    retries: int,
    rate_limiter: RequestRateLimiter,
) -> tuple[str, bool | None, str, str | None, str | None]:
    rate_limiter.wait()
    try:
        available, normalized, code = check_tag(tag, timeout, retries)
        return tag, available, normalized, code, None
    except EXPECTED_REQUEST_ERRORS as error:
        return tag, None, tag, None, str(error)


def read_completed(*paths: Path) -> set[str]:
    completed: set[str] = set()
    for path in paths:
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as handle:
            completed.update(line.strip().casefold() for line in handle if line.strip())
    return completed


def append_lines(path: Path, lines: list[str]) -> None:
    if not lines:
        path.touch(exist_ok=True)
        return
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write("".join(f"{line}\n" for line in lines))


def sort_result_file(path: Path, source_order: dict[str, int]) -> None:
    if not path.exists():
        return
    unique_lines: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            value = line.strip()
            if value:
                unique_lines.setdefault(value.casefold(), value)
    ordered = sorted(
        unique_lines.values(),
        key=lambda value: (source_order.get(value.casefold(), len(source_order)), value.casefold()),
    )
    path.write_text("".join(f"{line}\n" for line in ordered), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Find available Cloudflare Wallet tags.")
    parser.add_argument(
        "--input-file",
        type=Path,
        help="Check tags from this file in line order instead of generating combinations.",
    )
    parser.add_argument("--length", type=int, default=3, help="Tag length (default: 3).")
    parser.add_argument(
        "--category",
        choices=("all", "numeric", "alpha", "mixed"),
        default="all",
        help="Combination type to check (default: all).",
    )
    parser.add_argument("--delay", type=float, default=0.001, help="Seconds between requests (default: 0.001).")
    parser.add_argument("--workers", type=int, default=8, help="Concurrent request workers (default: 8).")
    parser.add_argument("--batch-size", type=int, default=100, help="Results saved per batch (default: 100).")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout in seconds.")
    parser.add_argument("--retries", type=int, default=4, help="Retries for rate limits and temporary failures.")
    parser.add_argument("--limit", type=int, help="Check at most this many unfinished tags.")
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Show progress every N checks (default: 25).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Result directory (default: results, or a dedicated directory for input files).",
    )
    parser.add_argument("--show-reserved", action="store_true", help="Also print reserved tags.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.length < 1:
        raise SystemExit("--length must be at least 1")
    if args.delay < 0 or args.timeout <= 0 or args.retries < 0:
        raise SystemExit("delay/retries must be non-negative and timeout must be positive")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    if args.progress_every < 1:
        raise SystemExit("--progress-every must be at least 1")
    if args.workers < 1 or args.batch_size < 1:
        raise SystemExit("--workers and --batch-size must be at least 1")

    if args.input_file:
        if not args.input_file.is_file():
            raise SystemExit(f"input file does not exist: {args.input_file}")
        source_tags = read_input_tags(args.input_file)
        total = len(source_tags)
        default_output_dir = Path("results") / f"{args.input_file.stem}_ordered"
        source_description = str(args.input_file)
        source_order = {tag.casefold(): index for index, tag in enumerate(source_tags)}
    else:
        source_tags = iter_tags(args.length, args.category)
        total = candidate_count(args.length, args.category)
        default_output_dir = Path("results")
        source_description = f"generated {args.length}-character {args.category} tags"
        source_order = None

    args.output_dir = args.output_dir or default_output_dir
    args.output_dir.mkdir(parents=True, exist_ok=True)
    available_path = args.output_dir / "available.txt"
    reserved_path = args.output_dir / "reserved.txt"
    errors_path = args.output_dir / "errors.jsonl"
    completed = read_completed(available_path, reserved_path)
    print(
        f"Starting scan from {source_description}: {total} tags; "
        f"{len(completed)} cached results will be skipped; "
        f"workers={args.workers}, batch={args.batch_size}.",
        file=sys.stderr,
        flush=True,
    )

    checked = 0
    available_count = 0
    pending_tags: Iterable[str] = (tag for tag in source_tags if tag.casefold() not in completed)
    if args.limit is not None:
        pending_tags = itertools.islice(pending_tags, args.limit)
    rate_limiter = RequestRateLimiter(args.delay)

    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="tag-check") as executor:
        try:
            for batch_number, batch in enumerate(iter_batches(pending_tags, args.batch_size), start=1):
                print(
                    f"Checking batch {batch_number}: @{batch[0]} through @{batch[-1]} ({len(batch)} tags)...",
                    file=sys.stderr,
                    flush=True,
                )
                futures = [
                    executor.submit(check_tag_safe, tag, args.timeout, args.retries, rate_limiter)
                    for tag in batch
                ]
                results_by_tag: dict[str, tuple[str, bool | None, str, str | None, str | None]] = {}

                for batch_finished, future in enumerate(as_completed(futures), start=1):
                    result = future.result()
                    tag = result[0]
                    results_by_tag[tag] = result

                    if (checked + batch_finished) % args.progress_every == 0:
                        print(
                            f"Completed {checked + batch_finished} this run; "
                            f"found {available_count} available...",
                            file=sys.stderr,
                            flush=True,
                        )

                available_lines: list[str] = []
                reserved_lines: list[str] = []
                error_lines: list[str] = []
                for input_tag in batch:
                    tag, available, normalized, code, error = results_by_tag[input_tag]
                    if error is not None:
                        error_lines.append(json.dumps({"tag": tag, "error": error}, ensure_ascii=True))
                    elif available:
                        available_lines.append(normalized)
                        available_count += 1
                        print(f"@{normalized} is available", flush=True)
                    else:
                        reserved_lines.append(normalized)
                        if args.show_reserved:
                            print(f"@{normalized} is already reserved")

                append_lines(available_path, available_lines)
                append_lines(reserved_path, reserved_lines)
                append_lines(errors_path, error_lines)
                if source_order is not None:
                    sort_result_file(available_path, source_order)
                    sort_result_file(reserved_path, source_order)
                checked += len(batch)
                print(
                    f"Saved batch {batch_number}: {len(available_lines)} available, "
                    f"{len(reserved_lines)} reserved, {len(error_lines)} errors.",
                    file=sys.stderr,
                    flush=True,
                )
        except KeyboardInterrupt:
            print("Stopped. Run the same command again to resume.", file=sys.stderr, flush=True)
            return 130

    print(f"Finished: checked {checked}; found {available_count} available.", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
