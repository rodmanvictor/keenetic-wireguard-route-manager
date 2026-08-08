

## Code Documentation


- Document code in a style close to PHPDoc: every non-trivial module, class, public function, method, and complex data contract should have a structured docblock/docstring with purpose, parameters, return value, raised errors, and relevant side effects.
- Keep documentation useful and current. Do not add empty boilerplate that repeats the function name or obvious type hints.
- When changing behavior, update the related docblocks/docstrings in the same change.



## Documentation Rules

Start every task by checking [docs/README.md](docs/README.md). Treat it as the top-level documentation map, not as the place for detailed notes. Then open the relevant folder `README.md` before changing that area.

All durable project documentation must live under `docs/` as separate Markdown files grouped by logical folder.
Documentation uses a two-level README system:

- `docs/README.md` links only to folder READMEes.
- Every logical docs folder must have its own `README.md`.
- Each folder `README.md` links to the detailed Markdown files inside that folder.
- Every link in `docs/README.md` and every folder `README.md` must include a short description after the link. Use the format `- [Title](file.md): description`. Do not leave bare link lists without descriptions.

When adding or changing a feature, task, service integration, command, schema, scoring rule, runbook, or operational finding:

1. Create or update the most specific Markdown file under the right `docs/` folder.
2. Update that folder's `README.md` in the same task so the new or changed file is discoverable.
3. Update [docs/README.md](docs/README.md) only when adding, removing, or renaming a documentation folder.
4. Do not bury detailed documentation inside `AGENTS.md` or `docs/README.md`.
5. If a new documentation category becomes necessary, create a logical folder and add it to the README.
6. Keep README descriptions current when a file's purpose changes.
7. Создай скрипт, который будет проверять, что бы были `README.md` файлы в папках, что бы каждый `README.md` описывал файлы в его иерархии и запускай его через Run `npm run docs:check`, когда надо проверить документацию или когда мы сильно переписываем документацию.
8. В папке docs хранить только устойчивое знание о системе. Для планов, чеклистов и т.д. используй папку plans
Use one file per major function, task, or service. Prefer names like `docs/pipeline/scoring.md`, `docs/services/rdrr.md`, or `docs/operations/live-collection.md`.
