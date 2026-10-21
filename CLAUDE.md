# Project rules

## Skill / plugin installs
- Before installing any agent skill or plugin (copying into a `skills/` dir, `git clone`, `claude plugin install`, etc.), run the `skill-inspector` skill on its source first.
- Proceed only on `APPROVE`; on `CAUTION` ask the user; on `REJECT` do not install.
- `.claude/hooks/skill-install-guard.py` enforces this as a PreToolUse hook (SkillSpector `DO_NOT_INSTALL` → deny, `CAUTION` or unscannable → ask).

## 掃描器 (alias)
- 「掃描器」 means the `skill-inspector` skill.
- When the user says 「幫我掃描一下再安裝」 (or similar, e.g. 「用掃描器掃過再裝」), first invoke `skill-inspector` on the skill's source, report the verdict in Chinese, then:
  - `APPROVE` → install it.
  - `CAUTION` → show the concerns and ask before installing.
  - `REJECT` → do not install; explain why.
