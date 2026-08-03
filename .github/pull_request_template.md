## Summary

-

## Validation

- [ ] `uv sync --frozen --extra dev`
- [ ] `uv run --frozen --extra dev pytest`
- [ ] `uv run --frozen --extra dev black --check .`
- [ ] `uv run --frozen --extra dev isort --check-only .`
- [ ] `uv build`

## Privacy / permissions checklist

- [ ] No recipient identifiers or message bodies are committed
- [ ] The MCP surface still contains exactly one send tool and no resources/prompts
- [ ] No message, Contacts, chat, attachment, or database reader was introduced
- [ ] Tool results, logs, process arguments, and environment variables do not expose send data
- [ ] Permission changes (if any) are documented in README/SECURITY notes
