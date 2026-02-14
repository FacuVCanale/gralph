# TODO

## Architecture & Communication
- [ ] Pass reports and progress context between agents.
- [ ] Implement "Allow All" permission mode: enable agents to automatically trigger and fix OS or environment-level failures.
- [ ] Evaluate if mutexes are actually necessary (currently unused by agents).
- [ ] Audit core requirements and remove unnecessary complexity.

## New Features
- [ ] Implement support for reading and resolving repository issues.
- [ ] Add direct task execution CLI:
    - **Single task**:
      ```bash
      gralph "add dark mode"
      gralph "fix the auth bug"
      ```
    - **Task list**:
      ```bash
      gralph              # defaults to PRD.md
      gralph --prd tasks.md
      ```
- [ ] Implement forceful init
