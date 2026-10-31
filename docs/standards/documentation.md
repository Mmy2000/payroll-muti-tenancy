# Documentation conventions

Documentation is part of the change. A pull request that changes behaviour, setup or a rule
updates the page that describes it, in the same pull request.

## Where things are written

| What | Where |
|---|---|
| What the product does, setup, production, features per area | `README.md` |
| The plan and the phases | `docs/PLAN.md` |
| The structure of the code, and the rules for writing it | `docs/standards/` |
| PayRole's rules, checked against its source | `docs/payrole-rules.md` |
| The mobile app's API | `docs/mobile-api.md` |
| Why a decision was made | `docs/decisions/` (ADRs) |
| Why a piece of code is the way it is | a comment or docstring next to it |

Put each fact in one place, and link to it from everywhere else. If a fact lives in the code
(a list of settings, a registry), document where to find it rather than copying it, unless the
copy is checked by a test.

## Writing

- Write for a developer who is new to the project but not to Django. Use the business's words
  and explain them once.
- State facts the code shows. Cite `path/to/file.py` (and `:line` when it helps). Don't
  describe intended behaviour as if it existed: an unbuilt piece is "not built yet" with a
  register entry.
- Prefer short pages with tables and examples taken from the real code over long prose.
- Diagrams: Mermaid in the Markdown (GitHub renders it), only when relationships are easier to
  see than to read.
- English. Arabic belongs in the UI translations, not the docs.

## Code comments and docstrings

See [coding conventions](coding.md#comments-and-docstrings). In short:

- Module and function docstrings say what and the non-obvious rules.
- Comments say why.
- `ADR-nnn` cites a decision.

## ADRs

See [decisions](../decisions/README.md) for when to write one and the template.

## Keeping it true

- Reviewers check that the docs touched by a change were updated.
- When you find a page that is wrong, fix it in your pull request.
