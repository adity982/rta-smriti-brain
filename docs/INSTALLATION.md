# Installation

Rta-Smriti Brain is a local Python application. The packaged dashboard is
included in the wheel, so normal users need only Python 3.11 or newer and Git.
Node.js is required only for dashboard development.

## Windows

Open PowerShell:

```powershell
git clone https://github.com/sulabhdubey/rta-smriti-brain.git
cd .\rta-smriti-brain
python --version
python .\rta-brain.py --json doctor

$RtaBin = "$env:LOCALAPPDATA\Rta-Smriti\bin"
python .\rta-brain.py --json install-local --target $RtaBin
$RtaBrain = Join-Path $RtaBin "rta-brain.cmd"
& $RtaBrain --json doctor
```

Use `& $RtaBrain` for later commands in that terminal. This does not require a
PATH change. To make `rta-brain` available in new terminals, add the printed
wrapper directory to your user PATH and restart PowerShell.

The recommended brain directory is:

```powershell
$BrainDir = "$env:USERPROFILE\Documents\Rta-Smriti\brains"
```

## macOS

Open Terminal. The Apple-provided system Python is not sufficient; install
Python 3.11 or newer first, for example with the official Python installer or
Homebrew.

```bash
git clone https://github.com/sulabhdubey/rta-smriti-brain.git
cd rta-smriti-brain
python3 --version
python3 ./rta-brain.py --json doctor

RTA_BIN="$HOME/.local/bin"
python3 ./rta-brain.py --json install-local --target "$RTA_BIN"
RtaBrain="$RTA_BIN/rta-brain"
"$RtaBrain" --json doctor
BrainDir="$HOME/.local/share/rta-smriti/brains"
```

The launcher is a local shell script, not a downloaded native application, so
it does not require an unsigned `.app` exception in Gatekeeper.

## Linux

Install Python 3.11 or newer, Python's `venv` support, and Git using your
distribution package manager. Then run:

```bash
git clone https://github.com/sulabhdubey/rta-smriti-brain.git
cd rta-smriti-brain
python3 --version
python3 ./rta-brain.py --json doctor

RTA_BIN="$HOME/.local/bin"
python3 ./rta-brain.py --json install-local --target "$RTA_BIN"
RtaBrain="$RTA_BIN/rta-brain"
"$RtaBrain" --json doctor
BrainDir="$HOME/.local/share/rta-smriti/brains"
```

## First Project

Windows:

```powershell
& $RtaBrain --json bootstrap-project C:\path\to\project --project project-name --brain-dir $BrainDir --write-agents
& $RtaBrain dashboard --brain-dir $BrainDir
```

macOS or Linux:

```bash
"$RtaBrain" --json bootstrap-project /path/to/project --project project-name --brain-dir "$BrainDir" --write-agents
"$RtaBrain" dashboard --brain-dir "$BrainDir"
```

Keep the dashboard terminal open and open the complete printed URL, including
its one-session `#token=...` fragment. The alpha runs in the foreground and does
not install a daemon or login item.

## Optional PATH Setup

On macOS or Linux, add this line to `~/.zshrc` or `~/.bashrc` if
`$HOME/.local/bin` is not already on PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Open a new terminal and run `rta-brain --json doctor`.

## Troubleshooting

- **`python` or `python3` is not found:** install Python 3.11 or newer and open a new terminal.
- **`connection refused`:** the foreground dashboard stopped. Run the dashboard command again and use its newly printed URL.
- **The dashboard opens but is unauthorized:** use the full current URL, including `#token=...`; tokens are deliberately replaced on each launch.
- **A wrapper is not found:** invoke the exact path returned by `install-local`, or add its directory to PATH.
- **A project is blocked:** run `self-check --check-files`; large or changed files remain fail-closed until re-indexed or the ingestion policy is deliberately changed.

## Uninstall

Delete the two generated wrappers (`rta-brain` and `rta-brain-mcp`, with `.cmd`
on Windows). Delete the cloned repository only after confirming you no longer
need it. Brain databases are separate and are never removed automatically;
delete your chosen brain directory only when you intend to erase its memories.
