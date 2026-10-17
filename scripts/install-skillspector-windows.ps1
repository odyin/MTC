<#
.SYNOPSIS
  One-click install of NVIDIA SkillSpector + a Claude Code hook that scans every
  agent skill before it is installed, for ALL projects on this Windows machine.

.DESCRIPTION
  1. Installs uv (if missing) and the skillspector CLI (pinned commit).
  2. Installs the guard hook to %USERPROFILE%\.claude\hooks\skill-install-guard.py
  3. Registers it as a PreToolUse hook in %USERPROFILE%\.claude\settings.json
     (existing settings are kept; a .bak backup is written first).
  4. Installs the skill-inspector skill to %USERPROFILE%\.claude\skills\skill-inspector
  5. Adds the "scan before install" rule to %USERPROFILE%\.claude\CLAUDE.md

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-skillspector-windows.ps1
.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install-skillspector-windows.ps1 -Uninstall
#>
[CmdletBinding()]
param([switch]$Uninstall)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

$Rev        = '3c8e4b958fda9602e0044885f766be0e49f03585'
$ClaudeDir  = Join-Path $env:USERPROFILE '.claude'
$HooksDir   = Join-Path $ClaudeDir 'hooks'
$GuardPath  = Join-Path $HooksDir 'skill-install-guard.py'
$Settings   = Join-Path $ClaudeDir 'settings.json'
$SkillDir   = Join-Path $ClaudeDir 'skills\skill-inspector'
$ClaudeMd   = Join-Path $ClaudeDir 'CLAUDE.md'
$MdBegin    = '<!-- skillspector-guard:begin -->'
$MdEnd      = '<!-- skillspector-guard:end -->'
$Utf8NoBom  = New-Object System.Text.UTF8Encoding $false

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    $msg" -ForegroundColor Green }

# Windows PowerShell 5.1 turns any stderr output of a native program into a terminating
# error when $ErrorActionPreference is 'Stop' and stderr is redirected. uv prints normal
# progress messages on stderr, so quiet native calls run with 'Continue' instead.
function Invoke-Quiet([scriptblock]$Block) {
    $old = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Block 2>&1 | Out-Null } finally { $ErrorActionPreference = $old }
}

function Add-UserBinToPath {
    $dirs = @((Join-Path $env:USERPROFILE '.local\bin'))
    if ($env:LOCALAPPDATA) { $dirs += (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links') }
    foreach ($bin in $dirs) {
        if (($env:Path -split ';') -notcontains $bin) { $env:Path = "$bin;$env:Path" }
    }
}

function Get-ToolPython {
    $toolDir = (& uv tool dir).Trim()
    return (Join-Path $toolDir 'skillspector\Scripts\python.exe')
}

# Adds or removes our PreToolUse entry in settings.json without touching anything else.
$MergeSource = @'
import json, os, shutil, sys

settings, mode = sys.argv[1], sys.argv[2]
data = {}
if os.path.exists(settings):
    with open(settings, encoding="utf-8-sig") as f:
        text = f.read().strip()
    data = json.loads(text) if text else {}
    shutil.copy2(settings, settings + ".bak")

hooks = data.setdefault("hooks", {})
pre = hooks.setdefault("PreToolUse", [])

def ours(entry):
    for h in entry.get("hooks", []):
        if "skill-install-guard" in h.get("command", "") + " ".join(h.get("args", [])):
            return True
    return False

pre[:] = [e for e in pre if not ours(e)]
if mode == "install":
    python, guard = sys.argv[3], sys.argv[4]
    hook = {"type": "command", "timeout": 300,
            "statusMessage": "SkillSpector: scanning skill before install..."}
    if " " in python or " " in guard:
        hook.update(command=python, args=[guard])        # exec form, no shell quoting
    else:
        hook["command"] = python + " " + guard            # works from Git Bash and PowerShell
    pre.append({"matcher": "Bash|PowerShell|Write|Edit", "hooks": [hook]})
if not pre:
    del hooks["PreToolUse"]
if not hooks:
    del data["hooks"]

os.makedirs(os.path.dirname(settings), exist_ok=True)
with open(settings, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
    f.write("\n")
'@

$GuardSource = @'
#!/usr/bin/env python3
"""PreToolUse hook: scan agent skills with SkillSpector before they are installed.

Covers:
  - Write/Edit of files under a `skills/` directory (e.g. .claude/skills/<name>/SKILL.md)
  - Bash/PowerShell commands that copy/clone/extract into a `skills/` directory
  - `claude plugin install` / `claude plugin marketplace add`

Verdicts from the SkillSpector recommendation:
  SAFE           -> no decision (normal permission flow), scan summary added to context
  CAUTION        -> "ask": the user must confirm
  DO_NOT_INSTALL -> "deny"
Anything that cannot be scanned (missing CLI, unresolved source, scan error) -> "ask".
Works on Linux, macOS and Windows (Git Bash and PowerShell paths).
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

SKILLS_DIR_RE = re.compile(r"(^|/)(\.claude/|\.agents/)?skills(/|$)", re.IGNORECASE)
INSTALL_VERB_RE = re.compile(
    r"\b(cp|mv|rsync|ln|install|git\s+clone|unzip|tar|curl|wget|copy|xcopy|robocopy|"
    r"copy-item|move-item|expand-archive|cpi|mi|invoke-webrequest|iwr)\b",
    re.IGNORECASE,
)
PLUGIN_INSTALL_RE = re.compile(r"\bclaude(\.exe)?\s+plugins?\s+(install|i|marketplace\s+add)\b", re.IGNORECASE)
GIT_URL_RE = re.compile(r"^(https?://|git@)\S+")
COPY_VERBS = {"cp", "mv", "rsync", "ln", "install", "copy", "xcopy", "robocopy", "copy-item", "move-item", "cpi", "mi"}
SCAN_TIMEOUT = 240


def norm(path):
    """Forward slashes, so one regex matches Windows and POSIX paths."""
    return path.replace("\\", "/")


def to_local_path(tok):
    """Expand ~ and turn Git Bash paths (/c/Users/...) into C:/Users/... on Windows."""
    tok = os.path.expanduser(tok)
    if os.name == "nt":
        m = re.match(r"^/([a-zA-Z])/(.*)$", tok)
        if m:
            tok = f"{m.group(1).upper()}:/{m.group(2)}"
    return tok


def emit(decision=None, reason="", context=""):
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse"}}
    if decision:
        out["hookSpecificOutput"]["permissionDecision"] = decision
        out["hookSpecificOutput"]["permissionDecisionReason"] = reason
    if context:
        out["hookSpecificOutput"]["additionalContext"] = context
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    sys.exit(0)


def find_skillspector():
    # Prefer the copy next to this interpreter (the uv tool venv), then PATH.
    exe_dir = os.path.dirname(sys.executable)
    for name in ("skillspector.exe", "skillspector"):
        candidate = os.path.join(exe_dir, name)
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("skillspector")


def scan(target):
    """Return (recommendation, summary) for one target path or URL."""
    cli = find_skillspector()
    if not cli:
        return None, "skillspector CLI is not installed"
    with tempfile.TemporaryDirectory() as tmp:
        report = os.path.join(tmp, "report.json")
        try:
            subprocess.run(
                [cli, "scan", target, "--no-llm", "--format", "json", "--output", report],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=SCAN_TIMEOUT, cwd=tmp,
            )
            with open(report, encoding="utf-8") as f:
                data = json.load(f)
        except (subprocess.TimeoutExpired, OSError, ValueError) as e:
            return None, f"scan of {target} failed: {e}"
    risk = data.get("risk_assessment", {})
    rec = risk.get("recommendation", "CAUTION")
    issues = data.get("issues", [])
    top = "; ".join(
        f"{i.get('id', '?')} {i.get('severity', '?')} {i.get('category', '')}: {i.get('pattern', '')}"
        for i in issues[:5]
    )
    summary = (
        f"SkillSpector {target}: score {risk.get('score')}/100, severity {risk.get('severity')}, "
        f"recommendation {rec}, {len(issues)} issue(s)" + (f" [{top}]" if top else "")
    )
    return rec, summary


def decide(results):
    """results: list of (recommendation, summary)."""
    summaries = "\n".join(s for _, s in results)
    recs = [r for r, _ in results]
    if "DO_NOT_INSTALL" in recs:
        emit("deny", "Skill install blocked by SkillSpector (DO_NOT_INSTALL). Run the skill-inspector "
                     "skill for a full review.\n" + summaries)
    if None in recs or "CAUTION" in recs:
        emit("ask", "SkillSpector could not clear this skill install; review before approving.\n" + summaries)
    emit(context="Pre-install SkillSpector scan passed.\n" + summaries)


def handle_file(tool_input, tool_name):
    path = tool_input.get("file_path", "")
    if not SKILLS_DIR_RE.search(norm(path)):
        sys.exit(0)
    content = tool_input.get("content") if tool_name == "Write" else tool_input.get("new_string")
    if not content:
        sys.exit(0)
    with tempfile.TemporaryDirectory() as tmp:
        staged = os.path.join(tmp, os.path.basename(norm(path)) or "SKILL.md")
        with open(staged, "w", encoding="utf-8") as f:
            f.write(content)
        decide([scan(staged)])


def handle_command(command, posix):
    if PLUGIN_INSTALL_RE.search(command):
        emit("ask", "Plugin install detected. The plugin's source is not scanned automatically: run the "
                    "skill-inspector skill on its repository first, then approve.")
    if not (SKILLS_DIR_RE.search(norm(command)) and INSTALL_VERB_RE.search(command)):
        sys.exit(0)
    try:
        tokens = shlex.split(command, posix=posix)
    except ValueError:
        tokens = command.split()
    tokens = [t.strip("'\"") for t in tokens]
    # For copy-style commands the last argument is the destination, not a source.
    if tokens and os.path.basename(norm(tokens[0])).lower() in COPY_VERBS:
        tokens = tokens[1:-1]
    targets = []
    for tok in tokens:
        if GIT_URL_RE.match(tok):
            targets.append(tok)
            continue
        if tok.startswith("-"):
            continue
        local = to_local_path(tok)
        if os.path.exists(local):
            targets.append(local)
    if not targets:
        emit("ask", "Command writes into a skills directory but no scannable source was found. "
                    "Scan it with the skill-inspector skill before approving.")
    decide([scan(t) for t in dict.fromkeys(targets)])


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        sys.exit(0)
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}
    if tool_name in ("Write", "Edit"):
        handle_file(tool_input, tool_name)
    elif tool_name == "Bash":
        handle_command(tool_input.get("command", ""), posix=True)
    elif tool_name == "PowerShell":
        handle_command(tool_input.get("command", ""), posix=False)
    sys.exit(0)


if __name__ == "__main__":
    main()
'@

$ClaudeMdBlock = @"
$MdBegin
## Skill / plugin installs
- Before installing any agent skill or plugin (copying into a ``skills`` folder, ``git clone``, ``claude plugin install``, etc.), run the ``skill-inspector`` skill on its source first.
- Proceed only on ``APPROVE``; on ``CAUTION`` ask the user; on ``REJECT`` do not install.
- ``~/.claude/hooks/skill-install-guard.py`` enforces this as a PreToolUse hook (SkillSpector ``DO_NOT_INSTALL`` = deny, ``CAUTION`` or unscannable = ask).
$MdEnd
"@

function Invoke-Merge([string]$mode, [string]$python) {
    $tmp = Join-Path ([IO.Path]::GetTempPath()) ("skillspector-merge-" + [guid]::NewGuid() + ".py")
    [IO.File]::WriteAllText($tmp, $MergeSource, $Utf8NoBom)
    try {
        if ($mode -eq 'install') {
            & $python -I $tmp $Settings install ($python -replace '\\', '/') ($GuardPath -replace '\\', '/')
        } else {
            & $python -I $tmp $Settings uninstall
        }
        if ($LASTEXITCODE -ne 0) { throw "Updating $Settings failed (exit $LASTEXITCODE)." }
    } finally { Remove-Item $tmp -ErrorAction SilentlyContinue }
}

function Remove-ClaudeMdBlock {
    if (-not (Test-Path $ClaudeMd)) { return }
    $text = [IO.File]::ReadAllText($ClaudeMd)
    $pattern = '(?s)\r?\n?' + [regex]::Escape($MdBegin) + '.*?' + [regex]::Escape($MdEnd) + '\r?\n?'
    [IO.File]::WriteAllText($ClaudeMd, [regex]::Replace($text, $pattern, "`n"), $Utf8NoBom)
}

# ---------------------------------------------------------------- uninstall
if ($Uninstall) {
    Add-UserBinToPath
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $py = Get-ToolPython
        if ((Test-Path $py) -and (Test-Path $Settings)) { Step 'Removing hook from settings.json'; Invoke-Merge 'uninstall' $py }
        Step 'Uninstalling skillspector'
        Invoke-Quiet { uv tool uninstall skillspector }
    }
    Remove-Item $GuardPath -Force -ErrorAction SilentlyContinue
    Remove-Item $SkillDir -Recurse -Force -ErrorAction SilentlyContinue
    Remove-ClaudeMdBlock
    Ok 'Uninstalled. Restart Claude Code to apply.'
    return
}

# ---------------------------------------------------------------- install
Step 'Checking prerequisites'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git is required (Claude Code on Windows also needs Git for Windows). Install it with: winget install --id Git.Git -e   then re-run this script.'
}
Add-UserBinToPath
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Step 'Installing uv (https://docs.astral.sh/uv/)'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id astral-sh.uv -e --accept-source-agreements --accept-package-agreements
    } else {
        powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    }
    Add-UserBinToPath
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'uv was installed but is not on PATH. Open a new terminal and re-run this script.' }
}
Ok ("uv " + (& uv --version))

Step "Installing skillspector (pinned to $($Rev.Substring(0,7)))"
& uv tool install --force --python 3.12 "skillspector[mcp] @ git+https://github.com/NVIDIA/skillspector.git@$Rev"
if ($LASTEXITCODE -ne 0) { throw 'skillspector install failed.' }
Invoke-Quiet { uv tool update-shell }
$Py = Get-ToolPython
if (-not (Test-Path $Py)) { throw "Could not find the skillspector Python at $Py" }
Ok (& (Join-Path (Split-Path $Py) 'skillspector.exe') --version)

Step "Writing guard hook to $GuardPath"
New-Item -ItemType Directory -Force -Path $HooksDir | Out-Null
[IO.File]::WriteAllText($GuardPath, $GuardSource, $Utf8NoBom)

Step "Registering hook in $Settings (backup: settings.json.bak)"
Invoke-Merge 'install' $Py

Step "Installing skill-inspector skill to $SkillDir"
New-Item -ItemType Directory -Force -Path $SkillDir | Out-Null
Invoke-WebRequest -UseBasicParsing -OutFile (Join-Path $SkillDir 'SKILL.md') `
    -Uri "https://raw.githubusercontent.com/NVIDIA/SkillSpector/$Rev/skills/skill-inspector/SKILL.md"

Step "Adding the install rule to $ClaudeMd"
Remove-ClaudeMdBlock
$existing = if (Test-Path $ClaudeMd) { [IO.File]::ReadAllText($ClaudeMd).TrimEnd() + "`n`n" } else { '' }
[IO.File]::WriteAllText($ClaudeMd, $existing + $ClaudeMdBlock + "`n", $Utf8NoBom)

Step 'Self-test'
$harmless = '{"tool_name":"Bash","tool_input":{"command":"dir"}}' | & $Py $GuardPath
if ($harmless) { throw "Guard produced output for a harmless command: $harmless" }
$probe = @{ tool_name = 'Write'; tool_input = @{ file_path = 'C:/Users/x/.claude/skills/probe/SKILL.md'; content = "---`nname: probe`ndescription: Formats dates.`n---`nFormat the date the user gives as YYYY-MM-DD.`n" } } | ConvertTo-Json -Compress
$verdict = $probe | & $Py $GuardPath | ConvertFrom-Json
$ctx = $verdict.hookSpecificOutput.additionalContext
if ($ctx -notmatch 'recommendation SAFE') { throw "Self-test failed: SkillSpector did not scan the probe skill. Output: $($verdict | ConvertTo-Json -Compress)" }
Ok 'SkillSpector scanned a probe skill through the hook (SAFE).'


Write-Host ''
Ok 'Done. Restart Claude Code (close all sessions) so the new hook is loaded.'
Ok 'Every project on this machine now scans skills with SkillSpector before installing them.'
Ok 'Remove everything later with:  powershell -ExecutionPolicy Bypass -File .\install-skillspector-windows.ps1 -Uninstall'
