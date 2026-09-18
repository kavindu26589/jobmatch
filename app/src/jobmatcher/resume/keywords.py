"""Deterministic skill/keyword detection and experience estimation.

These functions are deliberately dependency-free and run before/alongside the
LLM: they power fast lexical scoring and act as a robust fallback when the
model is unavailable.
"""

from __future__ import annotations

import re
from collections import Counter

from ..domain.models import ResumeProfile

# Curated skill lexicon. Multi-word phrases are matched with flexible
# separators ("machine learning" == "machine-learning"); short, ambiguous
# tokens ("go") are intentionally excluded.
SKILL_LEXICON: tuple[str, ...] = (
    # Programming languages
    "python",
    "java",
    "javascript",
    "typescript",
    "c++",
    "c#",
    "c",
    "rust",
    "go programming",
    "golang",
    "swift",
    "kotlin",
    "scala",
    "ruby",
    "php",
    "perl",
    "r programming",
    "matlab",
    "objective-c",
    "dart",
    "elixir",
    "clojure",
    "haskell",
    "lua",
    "shell scripting",
    "bash",
    "powershell",
    "sql",
    "html5",
    "css3",
    "sass",
    "less",
    ".net",
    "assembly",
    "vba",
    "graphql",
    "rest api",
    # Web frameworks
    "react",
    "react.js",
    "react native",
    "angular",
    "vue.js",
    "svelte",
    "next.js",
    "nuxt",
    "remix",
    "django",
    "flask",
    "fastapi",
    "node.js",
    "express.js",
    "nestjs",
    "spring boot",
    "spring framework",
    "hibernate",
    "rails",
    "laravel",
    "symfony",
    "asp.net",
    "blazor",
    "flutter",
    "jquery",
    "bootstrap",
    "tailwind css",
    "hugo",
    "gatsby",
    "astro",
    "redux",
    "zustand",
    "react query",
    # Data / ML / AI
    "pandas",
    "numpy",
    "scikit-learn",
    "scikit learn",
    "tensorflow",
    "keras",
    "pytorch",
    "jax",
    "xgboost",
    "lightgbm",
    "transformers",
    "hugging face",
    "llm",
    "langchain",
    "langgraph",
    "rag",
    "embedding",
    "vector database",
    "faiss",
    "pinecone",
    "weaviate",
    "qdrant",
    "chromadb",
    "mlops",
    "data pipeline",
    "etl",
    "airflow",
    "dbt",
    "spark",
    "pyspark",
    "hadoop",
    "flink",
    "kafka",
    "kafka connect",
    "feature engineering",
    "model evaluation",
    "hyperparameter tuning",
    "prompt engineering",
    "fine-tuning",
    "neural networks",
    "deep learning",
    "machine learning",
    "supervised learning",
    "unsupervised learning",
    "reinforcement learning",
    "computer vision",
    "natural language processing",
    "nlp",
    "genai",
    "generative ai",
    "rag pipelines",
    "statistical analysis",
    "a/b testing",
    "time series",
    "data warehousing",
    "snowflake",
    "bigquery",
    "redshift",
    "databricks",
    "looker",
    "tableau",
    "power bi",
    "excel",
    "gsheets",
    "dax",
    "sql query optimization",
    # Cloud / infra
    "aws",
    "aws lambda",
    "ec2",
    "s3",
    "rds",
    "dynamodb",
    "ecs",
    "eks",
    "fargate",
    "cloudfront",
    "lambda",
    "azure",
    "azure functions",
    "azure devops",
    "google cloud",
    "gcp",
    "kubernetes",
    "k8s",
    "docker",
    "docker compose",
    "terraform",
    "pulumi",
    "ansible",
    "helm",
    "istio",
    "nginx",
    "caddy",
    "prometheus",
    "grafana",
    "datadog",
    "new relic",
    "sentry",
    "opentelemetry",
    "servicemesh",
    "serverless",
    "microservices",
    "distributed systems",
    "ci/cd",
    "github actions",
    "circleci",
    "jenkins",
    "gitlab ci",
    "argocd",
    "feature flags",
    "load balancing",
    "caching",
    "redis",
    "memcached",
    "rabbitmq",
    "celery",
    "grpc",
    "websockets",
    "event-driven architecture",
    # Databases
    "postgresql",
    "postgres",
    "mysql",
    "mariadb",
    "mongodb",
    "cassandra",
    "elasticsearch",
    "opensearch",
    "neo4j",
    "clickhouse",
    "influxdb",
    "sqlite",
    "oracle",
    "sql server",
    "cockroachdb",
    "scylladb",
    "indexes",
    "database design",
    # Security / quality
    "oauth2",
    "jwt",
    "saml",
    "sso",
    "owasp",
    "penetration testing",
    "security auditing",
    "compliance",
    "gdrp",
    "gdpr",
    "soc 2",
    "iso 27001",
    "zero trust",
    "secrets management",
    "unit testing",
    "integration testing",
    "e2e testing",
    "test automation",
    "pytest",
    "junit",
    "cypress",
    "playwright",
    "selenium",
    "mocha",
    "jest",
    "karate",
    "tdd",
    "bdd",
    # Soft skills / management
    "team leadership",
    "mentoring",
    "code review",
    "technical writing",
    "public speaking",
    "stakeholder management",
    "cross-functional collaboration",
    "agile",
    "scrum",
    "kanban",
    "lean",
    "design thinking",
    "product management",
    "roadmapping",
    "prioritization",
    "communication",
    "problem solving",
    "critical thinking",
    "project management",
    "risk management",
    "vendor management",
    "hiring",
    "onboarding",
    # Domain
    "saas",
    "fintech",
    "e-commerce",
    "healthtech",
    "adtech",
    "real-time systems",
    "high availability",
    "scalability",
    "observability",
    "chaos engineering",
    "performance tuning",
    "payments",
    "fraud detection",
    "recommendation systems",
    "search ranking",
    "crm",
    "erp",
    "analytics",
    "dashboarding",
    "data governance",
    "data modeling",
    "api design",
    "sdk development",
    "open source maintenance",
)

_NOISE_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "then",
        "else",
        "for",
        "with",
        "from",
        "by",
        "to",
        "of",
        "in",
        "on",
        "at",
        "as",
        "is",
        "are",
        "was",
        "were",
        "using",
        "used",
        "use",
        "using",
        "experience",
        "years",
        "work",
        "working",
        "role",
        "team",
        "company",
        "job",
        "description",
        "responsibilities",
        "required",
        "responsibilities",
        "skills",
        "preferred",
        "qualifications",
        "must",
        "have",
        "plus",
        "bonus",
        "benefits",
        "about",
        "who",
        "what",
        "how",
        "when",
        "why",
        "this",
        "that",
        "these",
        "those",
        "will",
        "would",
        "can",
        "could",
        "should",
        "shall",
        "our",
        "your",
        "their",
        "you",
        "we",
        "us",
        "its",
        "it",
        "who",
        "whom",
        "new",
        "senior",
        "junior",
        "mid",
        "level",
        "remote",
        "fulltime",
        "parttime",
        "contract",
        "employment",
        "opportunity",
        "position",
        "candidate",
        "applicant",
        "apply",
        "please",
        "focus",
        "areas",
        "built",
        "building",
        "develop",
        "developing",
        "design",
        "designed",
        "manage",
        "managing",
        "led",
        "support",
        "supporting",
        "ensure",
        "ensuring",
        "provide",
        "providing",
        "maintain",
        "maintenance",
        "improve",
        "improving",
    ]
)


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#]+", text.lower())


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    escaped = re.escape(phrase.lower())
    return re.compile(r"(?<![a-z0-9#+])" + escaped.replace(r"\ ", r"[\s\-/]*") + r"(?![a-z0-9#+])")


def _detect(entries: tuple[str, ...], text: str, excludes: set[str]) -> list[str]:
    normalized = re.sub(r"\s+", " ", text.lower())
    found: list[str] = []
    for phrase in sorted(entries, key=len, reverse=True):
        if phrase in excludes:
            continue
        if _phrase_pattern(phrase).search(normalized):
            found.append(phrase)
    return found


def detect_skills(text: str, *, excludes: set[str] | None = None) -> list[str]:
    """Return known skills mentioned in ``text``, longest-first."""
    return _detect(SKILL_LEXICON, text, excludes or set())


def keyword_frequency(text: str, *, top_n: int = 15) -> list[str]:
    """Most frequent meaningful terms in ``text``."""
    counts: Counter[str] = Counter()
    for token in tokenize(text):
        if token not in _NOISE_WORDS and len(token) > 2:
            counts[token] += 1
    return [word for word, _ in counts.most_common(top_n)]


_YEAR_RE = re.compile(r"(?<!\d)(19|20)\d{2}(?!\d)")
_CURRENT_MARKERS = {"present", "current", "now", "ongoing", "today"}


def estimate_years_experience(profile: ResumeProfile | None) -> float | None:
    """Estimate years of overlap-corrected work experience from date text."""
    if profile is None:
        return None
    intervals: list[tuple[int, int]] = []
    for entry in profile.experience:
        start = _parse_year(entry.start_date)
        end = _parse_year(entry.end_date)
        if end is None and entry.end_date and entry.end_date.lower() in _CURRENT_MARKERS:
            end = _current_year()
        if start is None or end is None:
            continue
        if end < start:
            start, end = end, start
        intervals.append((start, end))
    if not intervals:
        return None
    intervals.sort()
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1] + 1:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    total_years = sum(end - start for start, end in merged)
    return round(total_years, 1) if total_years else None


def _parse_year(value: str | None) -> int | None:
    if not value:
        return None
    match = _YEAR_RE.search(value)
    return int(match.group(0)) if match else None


def _current_year() -> int:
    from datetime import datetime

    return datetime.now().year
