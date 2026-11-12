"""A technical vocabulary used to spot requirements in a job description
that are NOT in the master profile. Those become honest gaps rather than
silently ignored terms."""
from __future__ import annotations

# Terms grouped only for readability; the matcher treats them as one set.
TECH_LEXICON: dict[str, list[str]] = {
    "languages": [
        "python", "java", "c++", "c#", "c", "rust", "go", "golang", "javascript",
        "typescript", "ruby", "php", "scala", "kotlin", "swift", "perl", "bash",
        "powershell", "r", "matlab", "sql", "assembly", "solidity",
    ],
    "security": [
        "penetration testing", "pentesting", "red team", "blue team", "purple team",
        "threat modelling", "threat modeling", "threat hunting", "threat intelligence",
        "incident response", "digital forensics", "malware analysis", "reverse engineering",
        "binary exploitation", "vulnerability management", "vulnerability assessment",
        "application security", "appsec", "devsecops", "cloud security", "network security",
        "endpoint security", "identity and access management", "iam", "zero trust",
        "cryptography", "encryption", "pki", "owasp", "mitre attack", "mitre att&ck",
        "siem", "soc", "soar", "edr", "xdr", "ids", "ips", "waf", "firewall",
        "security architecture", "secure code review", "static analysis", "sast", "dast",
        "fuzzing", "exploit development", "bug bounty", "detection engineering",
        "security operations", "grc", "compliance", "iso 27001", "soc 2", "nist",
        "pci dss", "gdpr", "risk assessment", "incident management", "ctf",
        "bot detection", "fraud detection", "anomaly detection", "abuse detection",
        "incident triage", "log analysis", "packet analysis", "incident handling",
    ],
    "security_tools": [
        "burp suite", "burpsuite", "wireshark", "metasploit", "nmap", "ghidra", "ida pro",
        "gdb", "splunk", "elastic", "elk", "crowdstrike", "sentinelone", "snort", "suricata",
        "zeek", "osquery", "semgrep", "sonarqube", "nessus", "qualys", "kali",
    ],
    "ml_ai": [
        "machine learning", "deep learning", "neural network", "nlp",
        "natural language processing", "computer vision", "llm", "large language model",
        "generative ai", "genai", "prompt engineering", "fine-tuning", "rag",
        "retrieval augmented generation", "vector database", "embeddings",
        "transformers", "pytorch", "tensorflow", "keras", "scikit-learn", "sklearn",
        "xgboost", "lightgbm", "pandas", "numpy", "mlops", "model deployment",
        "feature engineering", "langchain", "langgraph", "ai agents", "agentic",
        "hugging face", "mlflow", "a/b testing", "statistical modelling",
        "statistical modeling", "time series", "reinforcement learning",
    ],
    "data": [
        "data engineering", "data pipeline", "etl", "elt", "data warehouse", "data lake",
        "airflow", "dbt", "spark", "pyspark", "hadoop", "kafka", "flink", "snowflake",
        "bigquery", "redshift", "databricks", "data modelling", "data modeling",
        "data quality", "data governance", "tableau", "power bi", "looker",
        "data visualisation", "data visualization", "dashboards", "analytics",
        "mysql", "postgresql", "postgres", "sqlite", "mongodb", "redis",
        "elasticsearch", "cassandra", "dynamodb", "nosql",
    ],
    "engineering": [
        "rest api", "restful", "graphql", "grpc", "microservices", "distributed systems",
        "system design", "docker", "kubernetes", "k8s", "terraform", "ansible",
        "ci/cd", "jenkins", "github actions", "gitlab ci", "git", "linux", "unix",
        "windows", "aws", "azure", "gcp", "google cloud", "cloud", "serverless",
        "lambda", "observability", "monitoring", "logging", "telemetry", "prometheus",
        "grafana", "datadog", "agile", "scrum", "jira", "unit testing", "test automation",
        "tdd", "code review", "version control", "object oriented", "functional programming",
        "concurrency", "multithreading", "operating systems", "computer networks",
        "tcp/ip", "http", "dns", "tls", "ssl", "algorithms", "data structures",
        "react", "node.js", "django", "flask", "fastapi", "spring", "html", "css",
    ],
    "blockchain": [
        "blockchain", "smart contract", "smart contracts", "solidity", "web3",
        "cryptocurrency", "crypto", "defi", "nft", "nfts", "ethereum", "evm",
        "consensus", "digital asset", "digital assets", "wallet security",
        "on-chain", "zero knowledge", "zk", "custody",
    ],
    # Checkable security practices — a real gap here is a real gap.
    "security_practices": [
        "secure sdlc", "sdlc", "access control", "authentication",
        "authorisation", "authorization", "attack surface", "hardening",
        "defense in depth", "patch management", "security monitoring",
        "security engineering", "secure code review", "code review",
    ],
    # Job-description phrasing, not credentials. Every security role says
    # "security testing" and "technical documentation"; nobody either has or
    # lacks them. Downweighted, and never listed as something not to claim.
    "boilerplate": [
        "security review", "security reviews", "code analysis", "security testing",
        "secure development", "secure product development", "security policies",
        "security policy", "security framework", "security protection",
        "attack methods", "security controls", "security standards",
        "security awareness", "technical documentation", "emerging threats",
        "defense mechanisms",
    ],
    "quant": [
        "statistics", "probability", "linear algebra", "calculus", "optimisation",
        "optimization", "stochastic", "monte carlo", "quantitative analysis",
        "mathematical modelling", "mathematical modeling", "discrete mathematics",
    ],
    "soft": [
        "communication", "stakeholder management", "leadership", "mentoring",
        "collaboration", "problem solving", "cross-functional", "presentation",
        "documentation", "ownership", "teamwork", "analytical thinking",
        "attention to detail", "self-starter", "fast-paced",
        "industry trends", "best practices",
    ],
}

# Terms that are not evidence-checkable: soft skills and job-description
# boilerplate. Everybody claims them, so a missing one is not a real gap.
# They carry little weight and never appear in the "do not claim" list.
GENERIC_TERMS: set[str] = set(TECH_LEXICON["soft"]) | set(TECH_LEXICON["boilerplate"])

# Kept for backwards compatibility.
SOFT_TERMS: set[str] = GENERIC_TERMS

# Which subject area each lexicon group belongs to. A posting that says
# "security testing" is a security posting even though the phrase is boilerplate
# and proves nothing about the candidate, so group membership — not evidence —
# is what establishes the domain.
GROUP_DOMAIN: dict[str, tuple[str, ...]] = {
    "languages": ("programming",),
    "security": ("security",),
    "security_tools": ("security", "security-tools"),
    "security_practices": ("security",),
    "boilerplate": ("security",),
    "blockchain": ("blockchain",),
    "ml_ai": ("ml",),
    "data": ("data",),
    "engineering": ("engineering",),
    "quant": ("mathematics",),
    "soft": (),
}

TERM_DOMAIN: dict[str, tuple[str, ...]] = {}
for _group, _terms in TECH_LEXICON.items():
    for _t in _terms:
        TERM_DOMAIN.setdefault(_t, ())
        TERM_DOMAIN[_t] = tuple(
            dict.fromkeys(TERM_DOMAIN[_t] + GROUP_DOMAIN.get(_group, ()))
        )

ALL_TERMS: list[str] = sorted(
    {t for group in TECH_LEXICON.values() for t in group}, key=len, reverse=True
)

# Sections of a JD and how much weight a keyword found there carries.
SECTION_WEIGHTS: dict[str, float] = {
    "requirement": 1.0,
    "responsibility": 0.7,
    "preferred": 0.4,
    "other": 0.5,
}

REQUIREMENT_HEADERS = [
    "requirement", "qualification", "what you need", "what we are looking for",
    "what we're looking for", "who you are", "must have", "minimum", "basic qualification",
    "skills and experience", "you have", "essential",
]
PREFERRED_HEADERS = [
    "preferred", "nice to have", "bonus", "plus", "desirable", "advantageous",
    "good to have", "additional", "pluses",
]
RESPONSIBILITY_HEADERS = [
    "responsibilit", "what you will do", "what you'll do", "the role", "about the role",
    "your impact", "day to day", "day-to-day", "duties", "you will",
]
