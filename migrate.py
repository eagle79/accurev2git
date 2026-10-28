"""
AccuRev to Git Migration Tool.
Migrates transaction history from an AccuRev stream into a Git repository.

Usage:
    python migrate.py <accurevBranch> <repoLocation> [--since YYYY-MM-DD]
"""

import argparse
import getpass
import os
import signal
import subprocess
import sys
import time
from types import FrameType
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# Flag to track if shutdown has been requested (e.g., via Ctrl+C)
shutdown_requested = False


def handle_sigint(signum: int, frame: FrameType | None) -> None:
    """Signal handler for graceful shutdown on Ctrl+C."""

    global shutdown_requested
    if shutdown_requested:
        print("\n[FORCE EXIT] Exiting immediately.", file=sys.stderr)
        sys.exit(1)

    shutdown_requested = True
    print(
        "\n[INTERRUPT] Graceful shutdown requested. "
        "Finishing current operation...",
        file=sys.stderr
    )


# Register the signal handler for SIGINT (Ctrl+C)
signal.signal(signal.SIGINT, handle_sigint)


def format_time(seconds: float) -> str:
    """Formats seconds into a human-readable duration string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        return f"{hours}h {mins}m {secs}s"


def run_command(cmd: list[str], cwd: Path | None = None) -> str:
    """
    Runs a system command and returns stdout. Raises RuntimeError on
    failure.
    """

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Command failed: {' '.join(cmd)}", file=sys.stderr)
        print(f"[ERROR] Output: {e.stderr}", file=sys.stderr)
        raise RuntimeError(f"Command execution error: {e}") from e


def ensure_accurev_login(user: str | None, password: str | None) -> None:
    """
    Checks AccuRev session status. If unauthenticated, logs in using
    a non-expiring session (-n) to support long-running migrations.
    """
    print("Checking AccuRev authentication status...")
    try:
        # secinfo returns 'authuser', 'anyuser', or 'notauth'
        result = run_command(["accurev", "secinfo"])
        if "notauth" not in result.lower():
            print("[+] AccuRev session is active.")
            return
    except Exception:
        pass  # Fall through to login prompt if secinfo fails

    print("[!] AccuRev session not authenticated or expired.")

    if not user:
        user = input("AccuRev Username: ").strip()
    if not password:
        password = getpass.getpass("AccuRev Password: ")

    print(f"Logging in to AccuRev as '{user}' (non-expiring session)...")

    # -n creates a non-expiring session so it survives multi-day runs
    run_command(["accurev", "login", "-n", user, password])
    print("[+] AccuRev login successful.")


def get_commit_author(
    user: str,
    author_map: dict[str, str],
    default_email_domain: str
) -> tuple[str, str]:
    """Resolves an AccuRev user to Git author name and email."""

    if user in author_map:
        raw = author_map[user]
        name, email = raw.split("<")
        return name.strip(), email.rstrip(">").strip()

    clean_user = user.strip().lower()
    return user, f"{clean_user}@{default_email_domain}"


def get_accurev_history(
    stream_name: str,
    since_date: str | None = None
) -> tuple[list[dict], set[str]]:
    """
    Pulls and parses transaction XML history for the target stream, filtered
    natively at the server.
    """

    print(
        f"Fetching transaction history for AccuRev stream '{stream_name}'..."
    )

    cmd = ["accurev", "hist", "-s", stream_name, "-a"]

    if since_date:
        formatted_date = since_date.replace('-', '/')
        time_spec = f"{formatted_date} 00:00:00-now"
        cmd.extend(["-t", time_spec])
        print(f"Applying native server-side time filter: {time_spec}")

    cmd.append("-fx")

    xml_output = run_command(cmd)

    try:
        root = ET.fromstring(xml_output)
    except ET.ParseError as e:
        print("[ERROR] Failed to parse AccuRev XML output.", file=sys.stderr)
        raise SystemExit(1) from e

    transactions = []
    unique_users = set()
    for tx in root.findall(".//transaction"):
        tx_id = int(tx.attrib["id"])
        tx_type = tx.attrib.get("type", "").lower()
        user = tx.attrib.get("user", "accurev")
        time_epoch = int(tx.attrib.get("time", "0"))

        comment_elem = tx.find("comment")
        comment = (
            comment_elem.text.strip()
            if comment_elem is not None and comment_elem.text
            else f"AccuRev transaction {tx_id}"
        )

        # Skip dispatch transactions as they are not relevant for Git migration
        if tx_type == "dispatch":
            continue

        transactions.append({
            "id": tx_id,
            "user": user,
            "epoch": time_epoch,
            "comment": comment
        })
        unique_users.add(user)

    # Ensure chronological order (lowest transaction ID first)
    transactions.sort(key=lambda x: x["id"])

    return transactions, unique_users


def get_last_migrated_tx(repo_path: Path) -> int:
    """
    Scans existing Git log for the highest AccuRev transaction ID already
    committed.
    """

    git_dir = repo_path / ".git"
    if not git_dir.exists():
        return 0

    try:
        # Use --format=%B to inspect full raw commit messages (subject + body)
        result = subprocess.run(
            ["git", "log", "--format=%B"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True
        )

        tx_ids = []
        for line in result.stdout.splitlines():
            if "AccuRev-Tx:" in line:
                parts = line.split("AccuRev-Tx:")
                try:
                    tx_ids.append(int(parts[1].strip()))
                except ValueError:
                    pass

        return max(tx_ids) if tx_ids else 0

    except Exception:
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate an AccuRev stream's history to Git safely.")

    parser.add_argument(
        "accurevBranch",
        help="Name of the AccuRev stream/branch to migrate"
    )
    parser.add_argument(
        "repoLocation",
        help="Target folder for the Git repository"
    )
    parser.add_argument(
        "--since",
        help="Only migrate transactions >= this date (Format: YYYY-MM-DD)",
        default=None
    )
    parser.add_argument(
        "-u", "--user",
        dest="accurev_user",
        help=(
            "AccuRev username for automatic login. "
            "If not provided, interactive login is supported."
        ),
        default=None
    )
    parser.add_argument(
        "-p", "--password",
        dest="accurev_pass",
        help=(
            "AccuRev password for automatic login"
            "If not provided, interactive login is supported."
        ),
        default=None
    )

    args = parser.parse_args()

    stream = args.accurevBranch
    repo_path = Path(args.repoLocation).resolve()

    if args.since:
        try:
            datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            print(
                "[ERROR] --since date format must be strictly YYYY-MM-DD "
                "(e.g., 2026-01-01)", file=sys.stderr)
            sys.exit(1)

    # Configure fallback author mapping and email domain in case config.py is
    # missing
    author_map = {}
    default_email_domain = "example.com"

    # Load configuration from config.py if it exists. If not, use fallbacks.
    config_path = Path(__file__).parent / "config.py"
    if config_path.exists():
        try:
            import config  # noqa: F401
            author_map.update(config.AUTHOR_MAP)
            default_email_domain = getattr(
                config, "DEFAULT_EMAIL_DOMAIN", default_email_domain
            )
        except ImportError as e:
            print(
                f"[WARN] Failed to load configuration from {config_path}. "
                f"Using defaults. Error: {e}", file=sys.stderr
            )

    # Prepare repository directory
    if not repo_path.exists():
        repo_path.mkdir(parents=True, exist_ok=True)

    # Make sure AccuRev is logged in
    ensure_accurev_login(args.accurev_user, args.accurev_pass)

    # Fetch transactions from AccuRev
    transactions, unique_users = get_accurev_history(stream, args.since)

    if not transactions:
        print(
            "[WARNING] No transactions found matching your "
            "criteria / date filter.",
            file=sys.stderr
        )
        sys.exit(0)

    for user in sorted(unique_users):
        if user not in author_map:
            print(
                f"[WARNING] AccuRev user '{user}' not found in AUTHOR_MAP. "
                f"Git commit will default to "
                f"'{user} <{user}@{default_email_domain}>'."
            )

    print(
        f"Found {len(transactions)} total transaction(s) in the "
        f"{stream} stream."
    )

    # Check if we are resuming an interrupted migration
    last_migrated_tx = get_last_migrated_tx(repo_path)
    if last_migrated_tx > 0:

        # Filter out transactions that have already been processed
        transactions = [
            tx for tx in transactions if tx["id"] > last_migrated_tx
        ]

        print("\n==================================================")
        print(" [RESUME MODE ACTIVE]")
        print(f" Existing repository detected at: {repo_path}")
        print(f" Last successfully committed AccuRev Tx: {last_migrated_tx}")
        print(f" Remaining transactions to migrate: {len(transactions)}")
        print("==================================================\n")

        if not transactions:
            print(
                "[RESUME] All transactions have already been migrated! "
                "Nothing left to do."
            )
            sys.exit(0)

        print(
            "Resuming migration starting from AccuRev Transaction ID: "
            f"{transactions[0]['id']}\n"
        )

    # Give the user a chance to review before proceeding
    try:
        input(
            "\nPress Enter to continue with the migration, "
            "or Ctrl+C to abort..."
        )
    except (KeyboardInterrupt, EOFError):
        print("\n[ABORT] Migration canceled by user.", file=sys.stderr)
        sys.exit(0)

    # Make sure our repo is initialized
    git_dir = repo_path / ".git"
    if not git_dir.exists():
        print(f"Initializing new Git repository at '{repo_path}'...")
        run_command(["git", "init"], cwd=repo_path)

    print(f"Processing {len(transactions)} remaining transaction(s)...\n")

    # Get to work
    durations = []
    total_remaining = len(transactions)

    for idx, tx in enumerate(transactions, start=1):
        tx_start_time = time.perf_counter()

        tx_id = tx["id"]
        user = tx["user"]
        epoch = tx["epoch"]
        comment = tx["comment"]

        print(
            f"[{idx}/{len(transactions)}] Processing Tx {tx_id} by {user}..."
        )

        # Populate workspace state at this specific transaction
        try:
            run_command([
                "accurev", "pop",
                "-v", stream,
                "-t", str(tx_id),
                "-L", str(repo_path),
                "-R", ".",
                "-O"
            ])
        except RuntimeError:
            if shutdown_requested:
                print(
                    f"\n[SAFE EXIT] Interrupted during Accurev pop at "
                    f"Transaction {tx_id}. Exiting cleanly. ", file=sys.stderr
                )
            print(
                f"\n[NETWORK/CLI ERROR] Failed at Transaction {tx_id}. "
                "Safe to re-run script later to resume.", file=sys.stderr
            )
            sys.exit(0)

        pop_duration = time.perf_counter() - tx_start_time
        print(f"  ├─ Populate complete ({pop_duration:.1f}s).")

        # Stage changes in Git
        run_command(["git", "add", "-A"], cwd=repo_path)
        stage_duration = time.perf_counter() - tx_start_time - pop_duration
        print(f"  ├─ Staging complete ({stage_duration:.1f}s).")

        # Check if there are actual changes to commit
        status = run_command(["git", "status", "--porcelain"], cwd=repo_path)
        if not status:

            # Measure the duration for this transaction
            tx_duration = time.perf_counter() - tx_start_time
            durations.append(tx_duration)

            # Calculate ETA based on a rolling average
            window_size = min(len(durations), 15)
            recent_durations = durations[-window_size:]
            avg_duration = sum(recent_durations) / len(recent_durations)

            eta_seconds = avg_duration * (total_remaining - idx)

            print(
                f"  └─ Skipping Tx {tx_id} (No file changes detected) | "
                f"Took {tx_duration:.1f}s "
                f"| Est. remaining: {format_time(eta_seconds)}"
            )

            if shutdown_requested:
                print(
                    f"\n[SAFE EXIT] Safely stopped after Transaction {tx_id}.",
                    file=sys.stderr
                )
                break
            continue

        # Format author and timestamps
        author_name, author_email = get_commit_author(
            user, author_map, default_email_domain
        )
        commit_date = datetime.fromtimestamp(
            epoch,
            tz=timezone.utc).isoformat()

        commit_msg = f"{comment}\n\nAccuRev-Tx: {tx_id}"

        # Commit with historical AccuRev author and timestamp
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = author_name
        env["GIT_AUTHOR_EMAIL"] = author_email
        env["GIT_AUTHOR_DATE"] = commit_date
        env["GIT_COMMITTER_NAME"] = author_name
        env["GIT_COMMITTER_EMAIL"] = author_email
        env["GIT_COMMITTER_DATE"] = commit_date

        try:
            subprocess.run(
                ["git", "commit", "-m", commit_msg],
                cwd=repo_path,
                env=env,
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError:
            if shutdown_requested:
                print(
                    f"\n[SAFE EXIT] Interrupted during Git commit at "
                    f"Transaction {tx_id}. Exiting cleanly. ", file=sys.stderr
                )
                sys.exit(0)
            raise

        # Measure duration and calculate ETA
        tx_duration = time.perf_counter() - tx_start_time
        durations.append(tx_duration)

        avg_duration = sum(durations) / len(durations)
        eta_seconds = avg_duration * (total_remaining - idx)

        print(
            f"  └─ Committed Tx {tx_id} "
            f"| Took {tx_duration:.1f}s "
            f"| Est. remaining: {format_time(eta_seconds)}"
        )

        if shutdown_requested:
            print(
                f"\n[SAFE EXIT] Safely stopped after commiting "
                f"Transaction {tx_id}."
            )
            print(
                "You can re-run the script later to resume migration "
                "from this point."
            )
            break

    print("\n Migration completed successfully!")


if __name__ == "__main__":
    main()
