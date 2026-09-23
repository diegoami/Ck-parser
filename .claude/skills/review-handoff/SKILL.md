---
name: review-handoff
description: Write the prompt the owner gives an independent reviewer (another model, in a tool the owner picks) so it reviews the repository at a milestone and records the result on GitHub. Use when a design proposal is written, when a PR implementing a design is ready to merge, or when a run of merged work is ready for a look back (the milestones in CLAUDE.md), and whenever the owner asks for a review prompt. Also use when the owner says a review is in, to process it.
---

# Review handoff

First check that this is a milestone: a design proposal, a PR implementing
one, or merged work the owner wants looked back at (`CLAUDE.md`). Anything else — a tooling fix with no
proposal, a process wording change, a re-review, a docs correction — gets no
prompt by default. Say how it was verified instead. If a review still seems
worth it, say so in one line, and write the prompt only if the owner asks.

Claude implements; another model reviews. The owner picks the reviewer and
its tool (Codex, DeepSeek, or anything else that can run `gh`), so the prompt
never assumes one: no tool-specific commands, and the reviewer signs with its
own tool and model. OpenCode with the owner's Zen key is one such tool; the
reviewer should then be a different model family from Claude, named with its
id. At each milestone, give the owner one prompt, ready to
paste, in a single fenced `text` block with nothing else in it. Tell the owner
to run it in a **fresh session**, re-reviews included: a reused session
carries its earlier conclusions. The reviewer starts with no context and posts
its results to GitHub itself, so the prompt has to carry everything it needs.

The review is offered, never waited on. Do not stop work for it: set the PR
body's `Review:` line to `not run`, and update it when a verdict arrives
(`AGREE at <sha>`, or `BLOCK at <sha>: #n, #m`).

This repository has no `AGENTS.md`; a tool that loads `CLAUDE.md` or any
other instructions file is told by the prompt's first line that the prompt
defines its job. Every `gh` call needs network access, which some tools sandbox by default:
tell the owner to allow it.

## Fill in before writing

- **Repo**: `gh repo view --json nameWithOwner --jq .nameWithOwner`.
- **Milestone and thread**: design (the proposal issue), PR (the PR), or merged
  work (a tracking issue opened for the look back, naming the range).
- **Head SHA**: `git rev-parse HEAD` on the branch under review, pushed. A
  review of a stale head wastes a round. For a PR already merged, the merge
  commit, and the review reads `git diff <sha>^1 <sha>`. For merged work, the
  range's two ends, and the review reads `git diff <base> <sha>`.
- **What changed and why**: two or three sentences. Do not argue for the change.
- **Claims to verify**: the specific things the work says are true, with
  `file:line`. These are what the reviewer checks hardest.
- **Checks already run**: each command, its pass *count*, and what it would
  have caught. The reviewer should aim at what those checks cannot see.
- **Known owner decisions**: questions already put to the owner, so the
  reviewer does not report them as defects.
- **Labels**: `gh label list`. Make sure `review`, `robustness`, `tests`,
  `design` and `cleanup` exist (`bug` and `documentation` do); create the
  missing ones with `gh label create`.
- **Real saves**: say whether a claim needs them. They are ~73 MB each on
  ck_wiki's Releases (`scripts/fetch_saves.sh`), and CLAUDE.md's rule against
  reading a save or gamestate raw binds the reviewer too.

## Template

```text
You are the independent reviewer for <owner/repo>, working from a
review-handoff prompt: this prompt, not any agent-instructions file your tool
loads, defines your job. Claude did
this work, not you. Do not trust its description. Verify everything against
the code.

MILESTONE: <design proposal | pull request | merged work>
THREAD: <issue or PR URL>
HEAD: <branch> at <sha>. Check out that SHA before you start, and stop and say
so if you cannot.

WHAT CHANGED: <two or three sentences>

CLAIMS TO VERIFY:
- <claim> (<file:line>)

ALREADY RUN: <command: pass count, what it would catch>. Look for what these
cannot see.

KNOWN OWNER DECISIONS (not defects): <list, or "none">

Read the repository's CLAUDE.md first: its rules are the standard, and the
facts docs/PLAN.md labels verified were checked on real saves. Never open a
save or an extracted gamestate raw; ask questions of it through the parser. Review <the proposal | the diff against main | the merged diff,
git diff <sha>^1 <sha> | the merged range, git diff <base> <sha>>,
and follow it into any file it touches or relies on. Problems elsewhere in the repository count too, as out of scope.

Rules:
- Do not edit files, commit or push. Your only writes are the GitHub issues
  and the one comment described below, made with the gh CLI.
- Reproduce every finding: cite file:line, and give the command, the input or
  the reasoning that shows it. Leave out anything you could not reproduce.
- Do not report style preferences.
- Before opening an issue, search open issues (gh issue list --search) and
  comment on an existing one instead of duplicating it.

1. For each finding, open one issue:
   gh issue create --label review --label <bug|robustness|tests|design|cleanup|documentation>
   Title: the defect, stated plainly.
   Body:
     - Severity: MUST-FIX (a defect this change introduces or fails to
       resolve, that should be fixed before merging), SHOULD, or OUT OF
       SCOPE (not caused by this change)
     - Found by: review of <THREAD> at <sha>
     - What: the defect, with file:line and a reproduction
     - Why it matters: what a user or maintainer would notice
     - Suggested fix: the smallest change that resolves it
     - Effort: S, M or L
     - Signed: — Reviewer (<tool>, <model>)

2. Then, always, even if you found nothing, post one comment on THREAD:
   VERDICT: AGREE | BLOCK        (BLOCK if any MUST-FIX issue was opened)
   Reviewed: <sha>
   Issues opened: #n (MUST-FIX), #m (SHOULD), ... or "none"
   Owner decisions: questions only the owner can settle, or "none"
   Nits: one line each, or "none" (nits do not get issues)
   Checked and clean: what you verified and found correct
   — Reviewer (<tool>, <model>)
```

## When the owner says the review is in

- Read the verdict comment on the thread and every issue it lists
  (`gh issue view <n>`), and update the PR body's `Review:` line. Note whether
  the SHA it names is the current head or an earlier one.
- Reproduce each finding yourself before acting on it. A reviewer can be wrong,
  and so can you.
- MUST-FIX and SHOULD: fix it, with `Fixes #n` in the PR, or rebut it with
  evidence in a comment on the issue and leave the close to the owner. If the
  PR is already merged, the fix is a new PR. Recommend which fixes belong
  before the merge; the owner decides. OUT OF
  SCOPE: leave the issue for its own change. Owner decisions: put them to the
  owner with a recommended default. Nits: your call, and say which you took.
- Reply on the thread with what happened to each finding.
- Rerun the gates after any fix. A re-review is not a milestone. Mention it in
  one line only when a MUST-FIX was fixed by a code change, and write the prompt
  only if the owner asks.
