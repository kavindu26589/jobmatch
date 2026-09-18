"""jobmatcher: a production-grade job-matching agent system.

Two layers:

- ``jobmatcher`` itself — resume parsing, live job search, hybrid matching,
  resume-improvement reporting, and LangGraph orchestration.
- ``opencode-gateway`` (the ``gateway`` package) — an opencode-API-key
  compatible LLM client that this application and any third party can use.
"""

__version__ = "0.1.0"
