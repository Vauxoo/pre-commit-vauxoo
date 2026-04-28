---
name: "vauxoo-pre-commit"
description: >-
  Use this skill when you need to set up, execute, or troubleshoot pre-commit in Vauxoo and OCA repositories, or when preparing to commit code that must pass strict linting standards.
  Triggers on: 'vauxoo/**' repos, 'oca/**' repos, 'lint', 'pre-commit', 'format code', 'new project'.
last_validated: "2026-04-25"
---

# Skill: Vauxoo / OCA Pre-Commit Protocol

This skill enforces the mandatory linting and formatting standards required for any code landing in a `vauxoo/***` or `oca/***` Odoo repository.

> [!IMPORTANT]
> **This code will land in a strict CI environment.**
> If you do not pass these checks, the pipeline WILL fail, the Merge Request will be blocked, and you will put the next developer (or agent) through hell trying to clean up your mess.
> **DO NOT SILENCE LINTS** (`# noqa`, `# pylint: disable=...`) without explicit, documented permission from the user.

---

## 1. Installation & Environment Check

Before making your first commit in a new or recently cloned repository, you MUST verify that the git hooks are installed.

1. **Verify Installation:** Check if `.git/hooks/pre-commit` exists.
2. **Install if missing:** If it does not exist, you must install the hooks within the Python virtual environment:
   ```bash
   pip install pre-commit-vauxoo
   pre-commit install
   ```
3. **Never bypass:** Do not attempt to commit code if the repository does not have the pre-commit hook installed.

## 2. The Headless TTY Trap (Legacy Systems)

> [!WARNING]
> **Historical Context:** In headless AI agent environments, `git commit` does **NOT** have an interactive TTY.
> Legacy versions of the Vauxoo git hook (prior to PR #222) would prompt the user: *"Do you want to run pre-commit-vauxoo?"*. Without a TTY, this prompt silently failed or hung the agent indefinitely.

Because of this legacy trap on older repositories, **if you are unsure if the hook is updated, you must run the linter manually.**

## 3. Mandatory Execution Flow

1. **Run the linter explicitly:**
   ```bash
   pre-commit run --files <modified_file_1> <modified_file_2>
   ```
   *Or for all files:*
   ```bash
   pre-commit run -a
   ```

2. **Handle Formatting Auto-Fixes (Black, isort):**
   If the pre-commit output shows that files were modified/reformatted, your Git working tree is now dirty.
   - **ACTION:** You must run `git add <files>` again to stage the auto-formatted changes.

3. **Handle Linting Errors (Flake8, Pylint):**
   If the output shows errors (e.g., `F841 unused variable`):
   - **ACTION:** Stop, read the logs, fix the python code manually, `git add` the fixes, and run `pre-commit run` again until it passes cleanly.

4. **Commit:**
   Only execute `git commit` when you are absolutely certain the code passes the linters or the hook has auto-formatted and you have staged those changes.
