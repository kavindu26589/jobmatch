# jobmatcher

Agentic job-matching and resume-improvement system. Uses
[`opencode-gateway`](../gateway) (opencode-compatible LLM access) to:

- parse a resume into a structured profile (ATS-style),
- discover real jobs from the internet (no-key sources),
- rank jobs against the profile (hybrid lexical + LLM scoring),
- and produce a concrete improvement plan with before/after rewrites.

```bash
pip install -e ../gateway -e .[dev]
jobmatcher match resume.pdf --location="Remote" --query=python
jobmatcher agent resume.pdf "Which backend roles fit me best?"
```

Run the API server with: `jobmatcher serve`.

## Install notes

`opencode-gateway` is a sibling package in this monorepo. Install both with
`pip install -e ../gateway -e .` (the app works without it, but LLM features
need a gateway provider configured, see root `.env.example`).