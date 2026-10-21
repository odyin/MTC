# Project rules

## Skill / plugin installs
- Before installing any agent skill or plugin (copying into a `skills/` dir, `git clone`, `claude plugin install`, etc.), run the `skill-inspector` skill on its source first.
- Proceed only on `APPROVE`; on `CAUTION` ask the user; on `REJECT` do not install.
- `.claude/hooks/skill-install-guard.py` enforces this as a PreToolUse hook (SkillSpector `DO_NOT_INSTALL` → deny, `CAUTION` or unscannable → ask).
