# clipstack

A clipboard history manager for the terminal. Runs a background daemon that silently records everything you copy, stores the last 100 entries in a local sqlite database, and lets you browse and re-paste anything from your history.

## requirements

One of these for clipboard access:
- `xclip` or `xsel` on Linux/WSL2
- `pbpaste` / `pbcopy` on macOS (built-in)

`fzf` for the `pick` command — installed automatically if missing (Linux apt/snap).

## setup

Add this to your `.bashrc` or `.profile` so the daemon starts on login:

```bash
python /path/to/clipstack/main.py start

for using it, you can also add this:

alias clipstack='python /path/to/clipstack/main.py
```

That's the whole setup. It forks into the background, makes no noise, and starts recording copies immediately.

## commands

### daemon

```bash
clipstack start     # start the background watcher (safe to run multiple times)
clipstack stop      # shut it down
clipstack status    # check if it's running, how many entries are stored
```

### browsing history

```bash
clipstack list               # last 10 entries
clipstack list -n 25         # last 25 entries
clipstack list --page 2      # older entries, 10 per page
clipstack list --first       # oldest entries first
clipstack list --all         # everything

clipstack list --id 42       # print entry #42 in full and copy it to clipboard
```

Each entry shows an id, timestamp, and a truncated preview:

```
[  54]  02-25 15:58  def handle_request(self, path, params):  ...
[  53]  02-25 15:41  https://docs.python.org/3/library/sqlite3...
[  52]  02-25 14:30  hey, I recieved an email this morning tha...
```

### pick (interactive search)

```bash
clipstack pick
```

Opens fzf with your full history. Type to fuzzy search , results narrow and highlight in real time as you type. Arrow keys to move, enter to select.

After selecting, it prints a preview of the full content (up to 300 chars) so you can confirm it's the right thing before it lands on your clipboard:

```
selected:
------------------------------------------------------------
  def handle_request(self, path, params):
      ...
------------------------------------------------------------
copied to clipboard.
```

### maintenance

```bash
clipstack dedup    # remove duplicates from existing history (keeps most recent)
clipstack clear    # wipe everything
```

## how duplicates work

If you copy something that already exists in history, the old entry is deleted and the new one is inserted at the top. So your history always reflects the actual recency of your copies with no duplicates cluttering the list.

## files

| path | purpose |
|------|---------|
| `~/.clipstack.db` | sqlite database with all entries |
| `~/.clipstack.pid` | pid file for the daemon process |

## notes

- polls clipboard every 500ms, so there is a tiny lag before a copy is recorded
- only stores text. images and files are ignored (for now)
- the daemon cleans up duplicates from previous runs on startup
- works on Linux/WSL2 and macOS
