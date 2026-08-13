# Agent quality gate

- Run `just check` before handing off code changes. It is the intentionally small, non-mutating gate for Python and React.
- Run focused tests for the behavior you changed; the quality gate does not replace tests.
- Python functions exposed to the model as tools must have a useful summary and Google-style `Args:` entries for every parameter. `just tool-docs` enforces the generated tool-schema contract.
- Do not widen lint rules merely for style. Add a blocking rule only when it identifies a likely correctness or safety defect and the repository passes it.
