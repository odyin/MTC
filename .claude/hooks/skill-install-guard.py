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
