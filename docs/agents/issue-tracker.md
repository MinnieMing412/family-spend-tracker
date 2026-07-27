# Issue Tracker

## System

This project uses GitHub Issues:

- Repository: `MinnieMing412/family-spend-tracker`
- Tracker: <https://github.com/MinnieMing412/family-spend-tracker/issues>
- Product requirements: `docs/PRD.md`
- Agent implementation plan: `docs/specs/IMPLEMENTATION_PLAN.md`

## Triage labels

- `ready-for-agent`: Requirements and testing seams are defined; an agent may take the issue subject to its documented dependencies.
- `in-progress`: An agent is actively implementing the issue.
- `blocked`: Progress requires an unmet dependency, user decision, permission, or external state change.
- `needs-review`: Implementation is complete and awaits review or acceptance.

Closed issues represent completed work; no separate completed label is used.

## Workflow

1. Select a `ready-for-agent` issue whose dependencies are complete.
2. Assign the issue and replace `ready-for-agent` with `in-progress`.
3. Keep implementation within the phase ownership boundaries in the agent plan.
4. Link pull requests to the issue.
5. Use `blocked` only with a comment naming the exact blocker and next action.
6. Replace `in-progress` with `needs-review` when validation is complete.
7. Close the issue when its acceptance criteria and review are complete.

## Issue content

Every phase issue should retain these sections:

- Problem Statement
- Solution
- User Stories
- Implementation Decisions
- Testing Decisions
- Out of Scope
- Further Notes

The corresponding file under `docs/specs/` is the version-controlled specification. If an issue and its file disagree, update both in the same change.
