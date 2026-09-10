# custom-panel

## Project
Custom hosting/control panel built with Python Flask.

## Environment
- Ubuntu running inside Termux
- ARM64/aarch64
- Python virtual environment: ./venv
- Main application: app.py

## Rules

* Do not delete production data.
* Do not modify database schema without checking existing code first.
* Do not expose secrets from `.env` or any secret/credential file.
* Do not hardcode passwords, API keys, tokens, or other credentials.
* Preserve existing functionality unless explicitly asked to change it.
* Before changing authentication or authorization, inspect the complete authentication flow.
* Before changing system commands, inspect how they are currently executed.
* Before changing Nginx configuration or service behavior, inspect the current configuration and execution flow first.
* Prefer minimal, focused, and reversible changes.
* Do not make destructive production or system-level changes without explicit user approval.
* Do not delete, overwrite, or migrate production data without explicit user approval.
* Do not modify files outside the project directory unless explicitly required and approved.
* Check `git status` before making changes.
* Review the current Git diff before committing.
* Create a Git checkpoint before major changes.
* Prefer small, focused commits with descriptive commit messages.
* Do not create a commit automatically unless explicitly requested or the user has approved the commit.
* Do not push to GitHub unless explicitly requested by the user.
* Run relevant tests after modifications.
* Run `git diff --check` after modifications.
* Check Python syntax before considering a Python change complete.
* If a change fails testing, do not hide or ignore the failure; report it clearly.
* Never claim a change is complete without verifying the resulting state.
* Never assume a standard x86_64 Ubuntu environment.
* Always verify architecture, installed services, paths, permissions, and runtime behavior before making system-level changes.
* When uncertain about an existing behavior, inspect the code and configuration before making assumptions.


## Production
This project will eventually run on an Ubuntu/Termux server.

Never assume the environment is a standard x86_64 Ubuntu server.
Always verify architecture and installed services before making system-level changes.
