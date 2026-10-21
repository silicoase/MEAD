# Cross-provider tinkering example

This directory defaults to the Gemini 3.1 Flash-Lite matched pair: **10 agents per
run, 10 experiments per agent, control/interact only, one repetition**. The two
prompt files are exact copies from the first pilot. Setup iterations are recorded in the linked README.

The complete seven-model plan, settings and offline validation instructions are
in [the tinkering README](../../experiments/cross-provider-tinkering/README.md).
Provider pins are optional; the setup configs use automatic OpenRouter host selection and fallbacks.

```sh
uv run mad batch examples/cross-provider/experiment.toml --dry-run
```

Add `OPENROUTER_API_KEY` to the repository `.env` for future execution. Keep the
`--dry-run` flag while inspecting the plan; it needs no key and makes no API calls.
