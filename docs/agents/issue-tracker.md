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
2. Create the issue's documented `dev/phase-*` branch from the latest `main`.
3. Assign the issue and replace `ready-for-agent` with `in-progress`.
4. Keep implementation within the phase ownership boundaries in the agent plan.
5. Push implementation commits only to the phase branch.
6. Open a pull request from the phase branch into `main` and link it to the issue.
7. Use `blocked` only with a comment naming the exact blocker and next action.
8. Replace `in-progress` with `needs-review` when validation is complete.
9. Merge through the pull request after its checks and review are complete.
10. Close the issue when its acceptance criteria and review are complete.

## Branch policy

- Never implement a phase directly on `main`.
- Never push implementation commits directly to `main`.
- Each phase uses exactly one canonical branch named in its specification.
- Create a phase branch only after its dependencies have merged into `main`.
- Always branch from the latest remote `main`, not from another phase branch.
- Parallel phases branch independently from the same dependency-complete `main`.
- Merge phase branches through pull requests targeting `main`.
- Delete merged phase branches after the issue is closed.
- Repository administration and workflow-only changes use a descriptive `dev/*` branch and the same pull-request rule.

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
