#!/usr/bin/env python3
import os
import sys
import time
import sqlite3
import subprocess
import argparse
import signal
import textwrap
from pathlib import Path

DB_PATH       = Path.home() / ".clipstack.db"
PID_PATH      = Path.home() / ".clipstack.pid"
MAX_ENTRIES   = 100
POLL_INTERVAL = 0.5


def get_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("""
        create table if not exists clips (
            id integer primary key autoincrement,
            content text not null,
            copied_at integer not null
        )
    """)
    db.commit()
    return db


def read_clipboard():
    for cmd in [
        ["xclip", "-selection", "clipboard", "-o"],
        ["xsel", "--clipboard", "--output"],
        ["pbpaste"],
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode == 0:
                return r.stdout
        except FileNotFoundError:
            continue
    return None


def write_clipboard(text):
    for cmd in [
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
        ["pbcopy"],
    ]:
        try:
            subprocess.run(cmd, input=text.encode(), check=True)
            return True
        except FileNotFoundError:
            continue
    return False


def ensure_fzf():
    try:
        subprocess.run(["fzf", "--version"], capture_output=True, check=True)
        return
    except FileNotFoundError:
        pass

    print("fzf not found, installing via apt...")
    result = subprocess.run(["sudo", "apt", "install", "-y", "fzf"])
    if result.returncode != 0:
        print("apt failed, trying snap...")
        result = subprocess.run(["sudo", "snap", "install", "fzf"])
    if result.returncode != 0:
        print("could not install fzf automatically")
        print("install manually: https://github.com/junegunn/fzf#installation")
        sys.exit(1)
    print("fzf installed\n")


def dedupe_db(db):
    # keep only the most recent row per unique content
    db.execute("""
        delete from clips where id not in (
            select max(id) from clips group by content
        )
    """)
    db.commit()


def daemon_loop():
    db = get_db()
    dedupe_db(db)  # clean any existing dupes on startup
    last = None
    while True:
        current = read_clipboard()
        if current and current.strip():
            if current != last:
                # delete any existing copy of this content, then insert fresh on top
                db.execute("delete from clips where content = ?", (current,))
                db.execute(
                    "insert into clips (content, copied_at) values (?, ?)",
                    (current, int(time.time()))
                )
                db.execute(
                    "delete from clips where id not in "
                    "(select id from clips order by id desc limit ?)",
                    (MAX_ENTRIES,)
                )
                db.commit()
                last = current
        time.sleep(POLL_INTERVAL)


def start_daemon():
    if PID_PATH.exists():
        pid = int(PID_PATH.read_text().strip())
        try:
            os.kill(pid, 0)
            #print(f"daemon already running (pid {pid})")
            return
        except ProcessLookupError:
            PID_PATH.unlink()

    pid = os.fork()
    if pid > 0:
        #print(f"clipstack daemon started (pid {pid})")
        #print(f"db: {DB_PATH}")
        return

    # child: detach completely from terminal
    os.setsid()
    sys.stdout = open(os.devnull, "w")
    sys.stderr = open(os.devnull, "w")
    sys.stdin  = open(os.devnull, "r")

    PID_PATH.write_text(str(os.getpid()))

    def cleanup(sig, frame):
        PID_PATH.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    try:
        daemon_loop()
    finally:
        PID_PATH.unlink(missing_ok=True)


def stop_daemon():
    if not PID_PATH.exists():
        print("daemon is not running")
        return
    pid = int(PID_PATH.read_text().strip())
    try:
        os.kill(pid, signal.SIGTERM)
        print(f"daemon stopped (pid {pid})")
    except ProcessLookupError:
        print("daemon was not running")
    PID_PATH.unlink(missing_ok=True)


def status_daemon():
    if not PID_PATH.exists():
        print("daemon: stopped")
        return
    pid = int(PID_PATH.read_text().strip())
    try:
        os.kill(pid, 0)
        db = get_db()
        count = db.execute("select count(*) from clips").fetchone()[0]
        print(f"daemon: running (pid {pid})")
        print(f"stored: {count} / {MAX_ENTRIES} entries")
        print(f"db:     {DB_PATH}")
    except ProcessLookupError:
        print("daemon: stopped (stale pid file)")
        PID_PATH.unlink(missing_ok=True)


def fmt_time(ts):
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%m-%d %H:%M")


def print_entries(rows):
    if not rows:
        print("no entries found")
        return
    for row_id, content, ts in rows:
        preview = content.replace("\n", " ").replace("\t", " ").strip()
        if len(preview) > 72:
            preview = preview[:72] + "..."
        print(f"[{row_id:4}]  {fmt_time(ts)}  {preview}")


def cmd_list(args):
    db = get_db()

    if args.id is not None:
        row = db.execute(
            "select id, content, copied_at from clips where id = ?", (args.id,)
        ).fetchone()
        if not row:
            print(f"no entry with id {args.id}")
            sys.exit(1)
        row_id, content, ts = row
        print(f"[{row_id}] copied at {fmt_time(ts)}\n")
        print(content)
        write_clipboard(content)
        print(f"\ncopied to clipboard.")
        return

    if args.all:
        rows = db.execute(
            "select id, content, copied_at from clips order by id desc"
        ).fetchall()
        print_entries(rows)
        return

    page_size = args.n if args.n else 10

    if args.first:
        rows = db.execute(
            "select id, content, copied_at from clips order by id asc limit ?",
            (page_size,)
        ).fetchall()
        rows = list(reversed(rows))
    elif args.page:
        offset = (args.page - 1) * page_size
        rows = db.execute(
            "select id, content, copied_at from clips order by id desc limit ? offset ?",
            (page_size, offset)
        ).fetchall()
    else:
        rows = db.execute(
            "select id, content, copied_at from clips order by id desc limit ?",
            (page_size,)
        ).fetchall()

    total = db.execute("select count(*) from clips").fetchone()[0]
    print(f"showing {len(rows)} of {total} entries  (use --all to see everything)\n")
    print_entries(rows)


def cmd_pick(args):
    ensure_fzf()
    db = get_db()
    rows = db.execute(
        "select id, content, copied_at from clips order by id desc"
    ).fetchall()

    if not rows:
        print("clipstack is empty — copy something first and make sure the daemon is running")
        sys.exit(0)

    lines = []
    for row_id, content, ts in rows:
        preview = content.replace("\n", " ").replace("\t", " ").strip()
#         if len(preview) > 100:
#             preview = preview[:100] + "..."
        lines.append(f"{row_id}\t{fmt_time(ts)}  {preview}")

    fzf_input = "\n".join(lines).encode()

    import tempfile, os
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".clipstack")
    os.close(tmp_fd)

    tty = open("/dev/tty", "rb+", buffering=0)
    proc = subprocess.Popen(
        [
            "fzf",
            "--delimiter=\t",
            "--with-nth=2..",
            "--no-sort",
            "--height=50%",
            "--reverse",
            "--prompt=clipstack> ",
            "--info=inline",
        ],
        stdin=subprocess.PIPE,
        stdout=open(tmp_path, "wb"),
        stderr=tty,
    )
    proc.stdin.write(fzf_input)
    proc.stdin.close()
    returncode = proc.wait()
    tty.close()

    if returncode != 0:
        os.unlink(tmp_path)
        sys.exit(0)

    selected = open(tmp_path).read().strip()
    os.unlink(tmp_path)

    if not selected:
        sys.exit(0)
    row_id = int(selected.split("\t")[0])

    row = db.execute("select content from clips where id = ?", (row_id,)).fetchone()
    if not row:
        sys.exit(1)

    content = row[0]

    print("\nselected:")
    print("-" * 60)
    truncated = (
        content if len(content) <= 300
        else content[:300] + f"\n... ({len(content) - 300} more chars)"
    )
    print(textwrap.indent(truncated, "  "))
    print("-" * 60)

    write_clipboard(content)
    print("copied to clipboard.")


def cmd_clear(args):
    db = get_db()
    count = db.execute("select count(*) from clips").fetchone()[0]
    db.execute("delete from clips")
    db.commit()
    print(f"cleared {count} entries")


def cmd_dedup(args):
    db = get_db()
    before = db.execute("select count(*) from clips").fetchone()[0]
    # keep only the most recent id for each unique content
    db.execute("""
        delete from clips where id not in (
            select max(id) from clips group by content
        )
    """)
    db.commit()
    after = db.execute("select count(*) from clips").fetchone()[0]
    print(f"removed {before - after} duplicates ({after} entries remaining)")


def main():
    parser = argparse.ArgumentParser(
        prog="clipstack",
        description="clipboard history manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        examples:
          clipstack start          start daemon in background (silent)
          clipstack status         check if daemon is running
          clipstack stop           stop the daemon

          clipstack list           show last 10 entries
          clipstack list -n 25     show last 25 entries
          clipstack list --first   show oldest 10 entries
          clipstack list --page 2  page 2 (entries 11-20)
          clipstack list --all     show everything
          clipstack list --id 42   fetch entry #42 and copy it to clipboard

          clipstack pick           open fzf, search, preview, copy on enter
          clipstack clear          wipe all history
        """)
    )

    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("start",  help="start daemon in background")
    sub.add_parser("stop",   help="stop the daemon")
    sub.add_parser("status", help="show daemon status and entry count")
    sub.add_parser("pick",   help="fuzzy search history, preview and copy selection")
    sub.add_parser("clear",  help="wipe all history")
    sub.add_parser("dedup",  help="remove duplicate entries from existing history")

    p_list = sub.add_parser("list", help="show clipboard history with pagination")
    p_list.add_argument("-n",      type=int, metavar="N",    help="number of entries (default 10)")
    p_list.add_argument("--first", action="store_true",      help="show oldest entries instead of newest")
    p_list.add_argument("--page",  type=int, metavar="PAGE", help="page number (10 per page)")
    p_list.add_argument("--all",   action="store_true",      help="show all entries")
    p_list.add_argument("--id",    type=int, metavar="ID",   help="fetch by id and copy to clipboard")

    args = parser.parse_args()

    if args.cmd == "start":
        start_daemon()
    elif args.cmd == "stop":
        stop_daemon()
    elif args.cmd == "status":
        status_daemon()
    elif args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "pick":
        cmd_pick(args)
    elif args.cmd == "clear":
        cmd_clear(args)
    elif args.cmd == "dedup":
        cmd_dedup(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
