# CAM Command Decision Tree

> **Troubleshooting/runtime reference:** normal developer work should begin in
> CAM_Codx. The direct commands below remain supported for isolating CAM_CAM
> behavior, recovery, runtime development, and expert scripting.

> `cam chat` is not currently a complete general router. It guides and can run
> mining, but create/build and enhance/fix requests are explicitly not wired.
> Do not use it as evidence that CAM_Codx-style full routing exists.

Use this when the main question is simple:

> Which CAM command should I use for the job I have right now?

## Fast Rule

- `chat` = interactive mining guide; other intents are incomplete
- `mine` = learn from outside repos
- `evaluate` = inspect a repo
- `preflight` = clarify a build/repair contract before execution
- `enhance` = improve an existing repo
- `ideate` = invent a new app concept
- `create` = turn a request into a spec-backed build task
- `validate` = verify the result

If you are unsure where to start, use CAM_Codx. For raw mining diagnosis only:

```bash
cam chat
```

## Decision Tree

### 1. Do you want CAM to learn from other repos?

If **yes**, start with:

```bash
cam doctor keycheck --for mine --live
cam mine /path/to/repo-folder --target /path/to/target --max-repos 10 --depth 4 --max-minutes 30
```

Use this when:
- you want CAM memory enriched
- you want CAM to assimilate useful patterns from outside repos

Then decide what the real target is:
- CAM itself
- another existing repo
- a brand-new app

### 2. Is the target CAM itself?

If **yes**, use:

```bash
cam doctor keycheck --for mine --live
cam mine /path/to/repo-folder --target /Users/o2satz/multiclaw --max-repos 10 --depth 4 --max-minutes 30
cam learn report --limit 10
cam learn reassess --task "your next CAM improvement task" --limit 10
```

If you want CAM to actually change its own code after learning:

```bash
cam evaluate /Users/o2satz/multiclaw --mode quick
cam enhance /Users/o2satz/multiclaw --dry-run
cam enhance /Users/o2satz/multiclaw --max-tasks 5
```

Meaning:
- `mine` teaches CAM
- `enhance` changes CAM

### 3. Is the target an existing repo that already exists?

If **yes**, start with:

```bash
cam evaluate /path/to/existing-repo --mode quick
cam enhance /path/to/existing-repo --dry-run
```

If the plan looks good:

```bash
cam enhance /path/to/existing-repo --max-tasks 5
```

If you already have a specific pending task id (for example, one seeded by `cam ab-test start` or created manually) and want to run **only** that task, skipping evaluate and plan:

```bash
cam enhance /path/to/existing-repo --task-id <pending-task-uuid>
```

Use this when you want to:
- modernize structure
- improve security
- future-proof architecture
- troubleshoot or repair an existing codebase
- exercise one specific pre-seeded task (A/B experiments, regression reruns)

If you want outside-repo learning first:

```bash
cam doctor keycheck --for mine --live
cam mine /path/to/repo-folder --target /path/to/existing-repo --max-repos 10 --depth 4 --max-minutes 30
cam evaluate /path/to/existing-repo --mode quick
cam enhance /path/to/existing-repo --dry-run
```

### 4. Is the target a brand-new app that does not exist yet?

If **yes**, use:

```bash
cam doctor keycheck --for mine --live
cam mine /path/to/repo-folder --target /path/to/new-app --max-repos 10 --depth 4 --max-minutes 30
cam doctor keycheck --for ideate --live
cam ideate /path/to/repo-folder --ideas 3 --max-repos 4
cam preflight /path/to/new-app --repo-mode new --request "Build the selected concept"
cam create /path/to/new-app --repo-mode new --request "Build the selected concept" --max-minutes 20
cam validate --spec-file data/create_specs/<spec-file>.json --max-minutes 5
```

Use this when you want CAM to:
- synthesize several repos into something new
- generate a standalone tool or app
- create a new repo rather than improve an old one

## Short Examples

### Improve CAM itself

```bash
cam doctor keycheck --for mine --live
cam mine Repo2Eval --target /Users/o2satz/multiclaw --max-repos 20 --depth 4 --max-minutes 30
cam learn report --limit 10
```

### Improve another repo

```bash
cam evaluate /path/to/repo --mode quick
cam enhance /path/to/repo --dry-run
cam enhance /path/to/repo --max-tasks 5
```

### Build a new standalone app

```bash
cam doctor keycheck --for mine --live
cam mine Repo2Eval --target /path/to/new-app --max-repos 10 --depth 4 --max-minutes 30
cam doctor keycheck --for ideate --live
cam ideate Repo2Eval --ideas 3 --max-repos 4
cam create /path/to/new-app --repo-mode new --request "Build the selected concept" --max-minutes 20
cam validate --spec-file data/create_specs/<spec-file>.json --max-minutes 5
```

## Final Mental Model

- For normal user routing, start with CAM_Codx; use `chat` only for its current
  mining guide or runtime troubleshooting
- If the target already exists: start with `evaluate`
- If the task is ambiguous or expensive: run `preflight` before execution
- If the target does not exist yet: start with `mine` + `ideate` + `create`
- If the target is CAM itself: `mine` into CAM first, then `enhance` CAM if you want code changes
- Use `cam doctor ...`, `cam learn ...`, `cam task ...`, and `cam forge ...` as the preferred advanced grouped paths
