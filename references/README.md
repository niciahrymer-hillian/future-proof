# References

This folder contains annotated learning copies and documentation for the Future Proof Notes project.
The originals in `python/` and `docs/` stay clean — all comments, docstrings, and anatomy labels live here.

---

## Files

| File | Source | What it is |
|---|---|---|
| `notes0_annotated_cp.py` | `python/notes0.py` | Full annotated CLI — covers every layer: directory setup, data model, parsing, CRUD, search, stats, interactive mode, and the main entry point. Includes `[LAYER]`, `[FUNCTION]`, `[CLASS]`, `[PARAMETER]`, `[VARIABLE]`, and `[RETURN]` labels. |
| `notes_api_annotated_cp.py` | `python/notes_api.py` | Annotated FastAPI wrapper — explains the app object, Pydantic request models, startup hook, route handlers, and HTTP error mapping. |
| `notes-shell_annotated_cp.py` | `python/notes-shell.py` | Annotated starter shell — minimal REPL that shows the setup → loop → finish control-flow pattern, plus `EOFError`/`KeyboardInterrupt` handling. |
| `config_annotated_cp.py` | `python/config.py` | Annotated config — explains each exported constant, the `NOTES_HOME` env-var override pattern, and why centralising config matters. |
| `learningreference.md` | `docs/LEARNING_REFERENCE.md` | Running learning log — card-by-card progress, key design decisions, what each piece affects, and test strategy notes. |

---

## How to use these files

- **Learning**: read an annotated copy alongside the clean source to understand why each line exists.
- **Updating**: when you add a feature to a source file, add the corresponding annotated version here so the reference stays in sync.
- **Template**: this folder structure is reusable — copy it into a new project as a starting reference layer.
