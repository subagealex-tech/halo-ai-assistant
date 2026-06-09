#!/usr/bin/env python3
"""H.A.L.O. backend — multi-provider LLM + TTS proxy."""

import json
import logging
import os
import sqlite3
import sys
import time
import hashlib
import platform
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from openai import OpenAI

PORT = int(os.getenv("HALO_PORT", "8765"))

# ── Provider config ──
PROVIDERS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1-preview", "o1-mini"],
        "free_models": [],
        "tts": True,
        "free": False,
        "label": "OpenAI",
        "agent": True,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "models": [
            "anthropic/claude-3.5-sonnet", "meta-llama/llama-3.1-8b-instruct",
            "mistralai/mistral-7b-instruct", "google/gemini-2.0-flash",
            "deepseek/deepseek-r1", "deepseek/deepseek-chat",
        ],
        "free_models": ["meta-llama/llama-3.1-8b-instruct", "mistralai/mistral-7b-instruct"],
        "tts": False,
        "free": True,
        "label": "OpenRouter",
        "agent": True,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama3-70b-8192", "llama3-8b-8192", "mixtral-8x7b-32768", "gemma2-9b-it", "llama-3.3-70b-versatile"],
        "free_models": ["llama3-70b-8192", "llama3-8b-8192", "mixtral-8x7b-32768", "gemma2-9b-it", "llama-3.3-70b-versatile"],
        "tts": False,
        "free": True,
        "label": "Groq",
        "agent": True,
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "free_models": [],
        "tts": False,
        "free": False,
        "label": "DeepSeek",
        "agent": True,
    },
    "together": {
        "base_url": "https://api.together.xyz/v1",
        "models": ["meta-llama/Llama-3.3-70B-Instruct-Turbo", "mistralai/Mixtral-8x22B-Instruct-v0.1"],
        "free_models": [],
        "tts": False,
        "free": False,
        "label": "Together",
        "agent": True,
    },
    "opencode": {
        "base_url": "https://opencode.ai/zen/v1",
        "models": [
            "deepseek-v4-flash-free", "mimo-v2.5-free", "nemotron-3-ultra-free", "big-pickle",
            "gpt-5.5", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.2",
            "claude-opus-4.8", "claude-sonnet-4.6", "claude-haiku-4.5",
            "gemini-3.5-flash", "gemini-3.1-pro",
            "qwen3.7-max", "qwen3.7-plus",
            "deepseek-v4-flash", "deepseek-v4-pro",
            "kimi-k2.5", "kimi-k2.6",
            "minimax-m2.7", "minimax-m2.5",
            "glm-5.1", "glm-5",
            "grok-build-0.1",
        ],
        "free_models": ["deepseek-v4-flash-free", "mimo-v2.5-free", "nemotron-3-ultra-free", "big-pickle"],
        "tts": False,
        "free": True,
        "label": "OpenCode Zen",
        "agent": True,
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "models": ["llama3.2", "llama3.1", "mistral", "gemma2", "phi4", "qwen2.5", "deepseek-r1"],
        "free_models": ["llama3.2", "llama3.1", "mistral", "gemma2", "phi4", "qwen2.5", "deepseek-r1"],
        "tts": False,
        "free": True,
        "label": "Ollama",
        "agent": True,
    },
    "lmstudio": {
        "base_url": "http://localhost:1234/v1",
        "models": ["local-model"],
        "free_models": ["local-model"],
        "tts": False,
        "free": True,
        "label": "LM Studio",
        "agent": True,
    },
    "custom": {
        "base_url": "",
        "models": [],
        "free_models": [],
        "tts": False,
        "free": True,
        "label": "Custom",
        "agent": False,
    },
}

# ── MCP server definitions ──
MCP_SERVERS = [
    {"id": "filesystem", "name": "filesystem", "icon": "📁", "desc": "Read/write files, list directories", "protocol": "stdio", "endpoint": "local", "status": "online"},
    {"id": "github", "name": "github", "icon": "🔒", "desc": "PRs, issues, repos, code review", "protocol": "http", "endpoint": "api.github.com", "status": "online"},
    {"id": "git", "name": "git", "icon": "🌿", "desc": "Commit, branch, diff, log", "protocol": "stdio", "endpoint": "local", "status": "online"},
    {"id": "brave-search", "name": "brave-search", "icon": "🌐", "desc": "Web & local search", "protocol": "http", "endpoint": "api.search.brave.com", "status": "online"},
    {"id": "fetch", "name": "fetch", "icon": "🕸", "desc": "HTTP requests, scrape pages", "protocol": "http", "endpoint": "any", "status": "online"},
    {"id": "puppeteer", "name": "puppeteer", "icon": "🎭", "desc": "Browser automation, screenshots", "protocol": "stdio", "endpoint": "local", "status": "busy"},
    {"id": "sqlite", "name": "sqlite", "icon": "🗄", "desc": "Query databases, run SQL", "protocol": "stdio", "endpoint": "local", "status": "online"},
    {"id": "postgres", "name": "postgres", "icon": "🐘", "desc": "PostgreSQL explorer & queries", "protocol": "http", "endpoint": "localhost:5432", "status": "online"},
    {"id": "slack", "name": "slack", "icon": "📬", "desc": "Messages, channels, search", "protocol": "http", "endpoint": "slack.com/api", "status": "online"},
    {"id": "email", "name": "email", "icon": "📧", "desc": "Send & read emails", "protocol": "http", "endpoint": "smtp/imap", "status": "online"},
    {"id": "docker", "name": "docker", "icon": "🐳", "desc": "Containers, images, compose", "protocol": "stdio", "endpoint": "local", "status": "busy"},
    {"id": "jira", "name": "jira", "icon": "📋", "desc": "Issues, sprints, projects", "protocol": "http", "endpoint": "your-domain.atlassian.net", "status": "offline"},
    {"id": "confluence", "name": "confluence", "icon": "📝", "desc": "Wiki pages, search, spaces", "protocol": "http", "endpoint": "your-domain.atlassian.net", "status": "offline"},
    {"id": "figma", "name": "figma", "icon": "🎨", "desc": "Design files, components", "protocol": "http", "endpoint": "api.figma.com", "status": "offline"},
    {"id": "sentry", "name": "sentry", "icon": "⏱", "desc": "Errors, traces, performance", "protocol": "http", "endpoint": "sentry.io/api", "status": "online"},
    {"id": "linear", "name": "linear", "icon": "📊", "desc": "Issues, cycles, teams", "protocol": "http", "endpoint": "api.linear.app", "status": "offline"},
    {"id": "desktop", "name": "desktop", "icon": "🖥️", "desc": "Open files with system default applications", "protocol": "stdio", "endpoint": "local", "status": "online"},
    {"id": "app-launcher", "name": "app-launcher", "icon": "🚀", "desc": "Launch installed applications", "protocol": "stdio", "endpoint": "local", "status": "online"},
    {"id": "system-info", "name": "system-info", "icon": "⚙️", "desc": "Get OS, hardware, disk, and process information", "protocol": "stdio", "endpoint": "local", "status": "online"},
    {"id": "file-finder", "name": "file-finder", "icon": "🔍", "desc": "Search files across the filesystem by name or pattern", "protocol": "stdio", "endpoint": "local", "status": "online"},
]

# Active provider selection (env-based defaults)
ENV_PROVIDER = os.getenv("HALO_PROVIDER", "openai").lower()
ENV_API_KEY = os.getenv("HALO_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
ENV_MODEL = os.getenv("HALO_MODEL", "")
ENV_CUSTOM_BASE_URL = os.getenv("HALO_BASE_URL", "")


def resolve_active(provider_override=None):
    """Merge env defaults with runtime overrides from state file."""
    state = load_runtime_state()
    provider = provider_override or state.get("provider", ENV_PROVIDER)
    model = state.get("model") or ENV_MODEL
    base_url = state.get("base_url") or ENV_CUSTOM_BASE_URL
    # per-provider saved key takes priority over env key
    saved_keys = state.get("keys", {})
    api_key = saved_keys.get(provider) or ENV_API_KEY
    return provider, model, base_url, api_key, state

# TTS (always needs OpenAI key, or separate TTS provider)
TTS_API_KEY = os.getenv("HALO_TTS_API_KEY") or ENV_API_KEY
TTS_MODEL = os.getenv("HALO_TTS_MODEL", "gpt-4o-mini-tts")
TTS_VOICE = os.getenv("HALO_TTS_VOICE", "onyx")
TTS_ENABLED = bool(os.getenv("HALO_TTS_API_KEY") or os.getenv("OPENAI_API_KEY"))

# edge-tts: free high-quality offline TTS via Microsoft Edge service
EDGE_TTS_AVAILABLE = False
EDGE_TTS_VOICE = os.getenv("HALO_EDGE_TTS_VOICE", "en-US-AndrewNeural")
try:
    import edge_tts
    EDGE_TTS_AVAILABLE = True
except ImportError:
    pass

# ── Agent Router ──
def _route_to_agent(message: str, agents: list) -> str:
    """Pick the best agent using keyword matching. Fast, reliable, no extra LLM call."""
    msg = message.lower()

    # Score each agent by keyword relevance
    scores = []
    for a in agents:
        aid = a["id"]
        if aid == "halo":
            continue
        score = 0
        name = a["name"].lower()
        role = a["role"].lower()
        try: skills = json.loads(a.get("skills", "[]"))
        except: skills = []
        try: tools = json.loads(a.get("tools", "[]"))
        except: tools = []

        # Keywords per agent
        kw_map = {
            "coder": ["code", "program", "function", "class", "algorithm", "implement", "script", "python", "javascript", "typescript", "rust", "go lang", "write.*function", "write.*program", "reverse", "sort", "binary.*tree", "linked.list", "recursion", "oop"],
            "writer": ["write.*doc", "documentation", "readme", "article", "blog", "content", "essay", "story", "narrative", "prose", "grammar", "spelling", "format"],
            "researcher": ["research", "analyze", "investigate", "find.*information", "search.*web", "what is", "who is", "how does", "explain.*concept", "study", "paper", "source", "citation", "fact.check"],
            "debugger": ["debug", "error", "bug", "fix", "crash", "exception", "traceback", "stack.trace", "wrong.*output", "unexpected.*behavior", "broken", "issue.*with", "not.*working", "problem.*with"],
            "data-analyst": ["data", "analysis", "statistics", "chart", "graph", "visualization", "dataset", "csv", "pandas", "matplotlib", "trend", "correlation", "regression", "mean", "median", "distribution"],
            "devops": ["deploy", "docker", "kubernetes", "ci/cd", "pipeline", "infrastructure", "server", "nginx", "cloud", "aws", "azure", "gcp", "container", "orchestrate", "monitoring", "terraform"],
            "security": ["security", "vulnerability", "exploit", "injection", "xss", "csrf", "owasp", "penetration", "auth", "permission", "encrypt", "hash", "ssl", "tls", "threat", "malware"],
            "architect": ["architecture", "design.*system", "microservice", "scalab", "distributed", "high.*availab", "load.*balanc", "database.*design", "schema", "system.*design", "tech.*stack", "monolith", "migration"],
            "ui-designer": ["design", "ui", "ux", "interface", "layout", "color", "typography", "css", "animation", "responsive", "figma", "mockup", "wireframe", "prototype", "user.*experience", "visual.*design"],
            "reviewer": ["review.*code", "code.*review", "quality", "best.*practice", "style.*guide", "lint", "clean.*code", "technical.*debt", "refactor", "maintainab"],
            "db-expert": ["sql", "query", "database", "index", "table", "join", "migration", "schema", "postgres", "mysql", "sqlite", "mongodb", "redis", "normaliz", "optimize.*query"],
            "image-gen": ["image", "picture", "photo", "illustration", "art", "dall.e", "generate.*image", "create.*image", "draw", "visual.*generat", "graphic.*design", "digital.*art"],
            "product-manager": ["product", "roadmap", "requirement", "user.story", "feature.*priorit", "sprint", "backlog", "stakeholder", "market.*fit", "go.to.market", "mvp"],
            "qa-tester": ["test.*case", "qa", "quality.*assurance", "bug.*report", "test.*plan", "regression", "manual.*test", "automation.*test", "acceptance.*criteria"],
            "technical-writer": ["documentation", "api.*doc", "user.*guide", "tutorial", "readme", "wiki", "reference.*guide", "getting.*started", "quickstart"],
            "ml-engineer": ["machine.*learn", "deep.*learn", "neural.*network", "train.*model", "pytorch", "tensorflow", "loss.*function", "accuracy", "precision", "recall", "dataset.*prep", "feature.*engineer", "hyperparameter"],
            "game-dev": ["game", "unity", "godot", "unreal", "gameplay", "sprite", "animation.*game", "level.*design", "physics.*engine", "collision", "rendering"],
            "mobile-dev": ["mobile", "ios", "android", "react.native", "flutter", "swift", "kotlin", "app.*develop", "mobile.*app", "screen.*size", "responsive.*mobile"],
        }

        for kw in kw_map.get(aid, []):
            import re
            if re.search(kw, msg):
                score += 10

        # Boost if message mentions the name or role
        if any(w in msg for w in name.split()):
            score += 5
        if any(w in msg for w in role.split()):
            score += 3

        scores.append((score, aid))

    # Best score wins; if tie or no clear winner, return "halo"
    scores.sort(key=lambda x: -x[0])
    if scores and scores[0][0] > 0:
        return scores[0][1]
    return "halo"

# ── Database (persistent, stores state + memory + keys) ──
HERE = Path(__file__).resolve().parent
DB_PATH = os.getenv("HALO_DB_PATH", str(HERE / "halo.db"))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            tags TEXT DEFAULT '[]',
            source TEXT DEFAULT 'chat',
            ts REAL NOT NULL,
            links TEXT DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_memories_ts ON memories(ts DESC);
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            role TEXT DEFAULT '',
            icon TEXT DEFAULT '🤖',
            provider TEXT DEFAULT '',
            model TEXT DEFAULT '',
            system_prompt TEXT DEFAULT '',
            skills TEXT DEFAULT '[]',
            tools TEXT DEFAULT '[]',
            temperature REAL DEFAULT 0.7,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS conversations (
            agent_id TEXT PRIMARY KEY,
            messages TEXT NOT NULL DEFAULT '[]',
            updated_at REAL NOT NULL
        );
    """)
    conn.commit()
    conn.close()

def seed_default_agents():
    conn = get_db()
    existing = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
    now = time.time()
    defaults = [
        ("halo", "H.A.L.O.", "General assistant", "🤖", "", "", "", "[]", "[]", 0.7, now),
        ("coder", "Coder", "Code generation & review", "💻", "", "", "You are a senior software engineer. Write clean, efficient, well-structured code. Always explain your reasoning.", '["code","debug","refactor","test"]', '["file-edit","code-run","terminal","git"]', 0.3, now),
        ("writer", "Writer", "Content & documentation", "✍️", "", "", "You are a professional writer. Produce clear, engaging content with proper formatting.", '["docs","ui-ux","accessibility"]', '["summarize","translate","file-edit"]', 0.8, now),
        ("researcher", "Researcher", "Web research & analysis", "🔍", "", "", "You are a research analyst. Find and synthesize information from multiple sources.", '["web","memory","data-viz"]', '["web-fetch","search","pdf-reader"]', 0.5, now),
        ("debugger", "Debugger", "Troubleshooting & fixes", "🐛", "", "", "You are a debugging expert. Analyze errors, find root causes, and suggest or apply fixes.", '["debug","test","security","perf"]', '["file-edit","code-run","terminal"]', 0.3, now),
        ("data-analyst", "Data Analyst", "Data analysis & visualization", "📊", "", "", "You are a data analyst. Analyze data, generate statistics, create visualizations, and extract insights. Use Python pandas, matplotlib, and seaborn.", '["data-viz","code","memory"]', '["code-run","file-edit","search"]', 0.4, now),
        ("devops", "DevOps", "Infrastructure & deployment", "⚙️", "", "", "You are a DevOps engineer. Manage infrastructure, CI/CD, Docker, Kubernetes, and deployment pipelines. Prioritize reliability and security.", '["security","perf","code"]', '["terminal","docker","deploy","git"]', 0.4, now),
        ("security", "Security Auditor", "Security review & auditing", "🛡️", "", "", "You are a security auditor. Review code for vulnerabilities, suggest fixes, and follow OWASP best practices. Be thorough and specific.", '["security","code","debug","test"]', '["file-edit","code-run","terminal"]', 0.3, now),
        ("architect", "Architect", "System design & architecture", "🏗️", "", "", "You are a software architect. Design scalable systems, choose appropriate technologies, and produce clear architecture documentation.", '["api-design","docs","ui-ux","perf"]', '["file-edit","git","search"]', 0.5, now),
        ("ui-designer", "UI/UX Designer", "Interface & experience design", "🎨", "", "", "You are a UI/UX designer. Design beautiful, accessible, responsive interfaces. Expert in CSS, color theory, typography, and glassmorphism.", '["ui-ux","css","responsive","accessibility"]', '["file-edit","screenshot","deploy"]', 0.7, now),
        ("reviewer", "Code Reviewer", "Code quality & best practices", "👁️", "", "", "You are a code reviewer. Review code for quality, style, performance, and correctness. Provide constructive, specific feedback.", '["code","refactor","test","perf"]', '["file-edit","code-run","terminal","git"]', 0.4, now),
        ("db-expert", "Database Expert", "SQL & data modeling", "🗄️", "", "", "You are a database expert. Design schemas, write optimized queries, and handle migrations. Expert in SQL, indexes, and query planning.", '["code","perf"]', '["database","file-edit","terminal"]', 0.4, now),
        ("image-gen", "Image Generator", "AI image creation & art", "🎨", "", "", "You are an AI image generation specialist. You create SVG images. Generate SVG code directly in your response using ```svg ... ``` blocks, then save it using write_file. Be creative with gradients, paths, and shapes. After saving, tell the user the file path and describe what you created. Always use write_file to save the SVG so it persists.", '["code"]', '["file-edit"]', 0.7, now),
        ("math-solver", "Math Solver", "Mathematical & logical reasoning", "🔢", "", "", "You are a mathematics and logic expert. Solve complex math problems step-by-step, explain proofs, analyze algorithms, and handle numerical computations. Show all working clearly.", '["code","debug"]', '["code-run","file-edit","terminal"]', 0.3, now),
        ("creative-writer", "Creative Writer", "Creative writing & storytelling", "📖", "", "", "You are a creative writer. Write compelling stories, poems, scripts, and creative content. Use vivid language, strong narrative structure, and engaging dialogue.", '["docs","ui-ux"]', '["file-edit","translate","summarize"]', 0.9, now),
        ("translator", "Translator", "Multi-language translation", "🌐", "", "", "You are a professional translator. Translate accurately between languages while preserving tone, context, and cultural nuances. Handle idioms and technical terms appropriately.", '["docs","web"]', '["translate","summarize","web-fetch"]', 0.4, now),
        ("summarizer", "Summarizer", "Text summarization & extraction", "📝", "", "", "You are a summarization expert. Extract key points, create concise summaries, identify main ideas, and organize information hierarchically. Be brief and accurate.", '["web","memory","data-viz"]', '["web-fetch","search","summarize","pdf-reader"]', 0.3, now),
        ("tutor", "Tutor", "Educational explanations & teaching", "🎓", "", "", "You are a patient and knowledgeable tutor. Explain concepts clearly, provide examples, ask guiding questions, and adapt to the learner's level. Break down complex topics.", '["code","web","memory","data-viz"]', '["web-fetch","code-run","search","file-edit"]', 0.6, now),
        ("product-manager", "Product Manager", "Product strategy & requirements", "📋", "", "", "You are a product manager. Define product requirements, prioritize features, create roadmaps, write user stories, and analyze market fit. Use data-driven decision making.", '["web","memory","data-viz","docs"]', '["web-fetch","search","file-edit","summarize"]', 0.6, now),
        ("qa-tester", "QA Tester", "Testing & quality assurance", "🧪", "", "", "You are a QA engineer. Write test cases, perform manual and automated testing, report bugs, verify fixes, and ensure quality standards. Be thorough and methodical.", '["code","debug","security","perf"]', '["code-run","file-edit","terminal","git"]', 0.3, now),
        ("technical-writer", "Technical Writer", "Documentation & guides", "📚", "", "", "You are a technical writer. Create clear, comprehensive documentation, API references, tutorials, and user guides. Explain complex technical concepts in simple terms.", '["docs","code","ui-ux","accessibility"]', '["file-edit","summarize","search","web-fetch"]', 0.5, now),
        ("ml-engineer", "ML Engineer", "Machine learning & AI", "🧠", "", "", "You are an ML engineer. Design and train models, preprocess data, evaluate performance, and deploy ML pipelines. Expert in PyTorch, scikit-learn, and data preprocessing.", '["code","data-viz","debug","memory"]', '["code-run","file-edit","terminal","search"]', 0.3, now),
        ("game-dev", "Game Developer", "Game design & development", "🎮", "", "", "You are a game developer. Design game mechanics, implement gameplay, optimize performance, and create engaging player experiences. Knowledgeable in Unity, Godot, and game engines.", '["code","ui-ux","debug","perf"]', '["code-run","file-edit","terminal","git"]', 0.4, now),
        ("mobile-dev", "Mobile Developer", "iOS & Android development", "📱", "", "", "You are a mobile developer. Build cross-platform and native mobile apps. Expert in React Native, Flutter, Swift, and Kotlin. Focus on performance and UX.", '["code","ui-ux","debug","perf"]', '["code-run","file-edit","terminal","git"]', 0.4, now),
        ("sys-admin", "Sys Admin", "System administration & config", "🖥️", "", "", "You are a system administrator. Manage users, services, permissions, backups, and system configuration. Safe, deliberate operations with proper validation.", '["code","security","perf"]', '["terminal","file-edit","install","docker"]', 0.3, now),
        ("network-eng", "Network Engineer", "Network config & diagnostics", "🌐", "", "", "You are a network engineer. Configure networks, diagnose connectivity issues, manage firewalls, and optimize routing. Use standard diagnostic tools.", '["security","code"]', '["terminal","web-fetch","install"]', 0.4, now),
        ("cloud-arch", "Cloud Architect", "Cloud infrastructure & architecture", "☁️", "", "", "You are a cloud architect. Design and manage cloud infrastructure on AWS, GCP, and Azure. Expert in Terraform, Kubernetes, and serverless architectures.", '["code","security","perf"]', '["terminal","docker","deploy","git"]', 0.4, now),
        ("sre", "SRE", "Site reliability & incident response", "🔋", "", "", "You are a Site Reliability Engineer. Monitor systems, respond to incidents, automate operations, run post-mortems, and improve reliability. Data-driven operator.", '["code","debug","security","perf"]', '["terminal","docker","deploy","git","install"]', 0.3, now),
        ("legal", "Legal Assistant", "Legal document analysis & review", "⚖️", "", "", "You are a legal assistant. Review contracts, analyze legal documents, identify clauses and risks, ensure compliance, and summarize legal findings. Precise and thorough.", '["docs","web","memory"]', '["web-fetch","file-edit","search","summarize","pdf-reader"]', 0.4, now),
        ("finance", "Financial Analyst", "Financial analysis & modeling", "💰", "", "", "You are a financial analyst. Analyze budgets, create financial models, forecast trends, evaluate investments, and generate reports. Expert in Excel, SQL, and data analysis.", '["data-viz","code","memory"]', '["code-run","file-edit","search","web-fetch"]', 0.4, now),
        ("data-eng", "Data Engineer", "ETL, pipelines & data infrastructure", "🗃️", "", "", "You are a data engineer. Build and maintain data pipelines, ETL processes, data warehouses, and big data infrastructure. Expert in SQL, Spark, and streaming systems.", '["code","debug","perf"]', '["terminal","file-edit","code-run","git","install"]', 0.3, now),
        ("blockchain", "Blockchain Developer", "Smart contracts & dApps", "⛓️", "", "", "You are a blockchain developer. Design and implement smart contracts, build dApps, audit DeFi protocols, and work with Solidity, Rust, and web3 technologies.", '["code","debug","security"]', '["code-run","file-edit","terminal","git"]', 0.3, now),
        ("cybersec", "Cybersecurity Analyst", "Penetration testing & threat analysis", "🔐", "", "", "You are a cybersecurity analyst. Perform penetration testing, threat modeling, vulnerability assessment, and security audits. Expert in OWASP, MITRE ATT&CK, network security, and incident response. Always follow ethical guidelines.", '["security","code","debug","web"]', '["terminal","web-fetch","search","file-edit","install"]', 0.3, now),
        ("gitops", "GitOps Engineer", "CI/CD, Kubernetes & GitOps workflows", "🔄", "", "", "You are a GitOps engineer. Manage Kubernetes clusters, ArgoCD, Flux, CI/CD pipelines, and infrastructure-as-code. Expert in Helm, Kustomize, Terraform, and Git-based deployment strategies. Automate everything.", '["code","perf","security"]', '["terminal","docker","deploy","git","file-edit"]', 0.3, now),
        ("bioinf", "Bioinformatician", "Genomics, proteomics & computational biology", "🧬", "", "", "You are a bioinformatician. Analyze genomic data, protein structures, and biological sequences. Expert in BLAST, FASTA, GFF/GTF formats, Python bioinformatics libraries, and statistical methods for biological data. Work with FASTQ, BAM, VCF files.", '["code","data-viz","memory"]', '["code-run","file-edit","terminal","search","install"]', 0.3, now),
        ("lang-designer", "Language Designer", "Compiler design & programming languages", "🔷", "", "", "You are a programming language and compiler designer. Design syntax, semantics, type systems, and grammars. Build lexers, parsers, compilers, and interpreters. Expert in LLVM, ANTLR, parsing algorithms, and programming language theory.", '["code","debug","docs"]', '["code-run","file-edit","terminal","git"]', 0.3, now),
        ("robotics", "Robotics Engineer", "ROS, control systems & robot programming", "🤖", "", "", "You are a robotics engineer. Design and program robotic systems using ROS, control theory, computer vision, and sensor fusion. Expert in Python, C++, kinematic modeling, and simulation environments like Gazebo.", '["code","debug","perf"]', '["code-run","file-edit","terminal","git","install"]', 0.4, now),
        ("devex", "Developer Experience", "Productivity, DX & workflow automation", "⚡", "", "", "You are a Developer Experience (DevEx) engineer. Improve developer productivity through automation, tooling, documentation, and streamlined workflows. Expert in shell scripting, build systems, dev containers, and developer portal design.", '["code","docs","perf","ui-ux"]', '["terminal","git","file-edit","code-run","install","deploy"]', 0.5, now),
        ("opencode", "OpenCode AI", "OpenCode CLI expert & automation", "🐙", "", "", "You are an OpenCode AI specialist. Expert in the OpenCode CLI tool — its commands, configuration, agent system, tool use, MCP servers, and workflow automation. You help users write efficient prompts, configure providers, manage agents, create custom skills, and automate software engineering workflows using OpenCode. You know about .opencode configuration, custom slash commands, agent delegation, file operations, and all built-in tools.", '["code","web","docs","debug","refactor"]', '["terminal","web-fetch","file-edit","code-run","search","git","install","deploy"]', 0.4, now),
    ]
    conn.executemany("INSERT OR IGNORE INTO agents (id,name,role,icon,provider,model,system_prompt,skills,tools,temperature,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", defaults)
    conn.commit()

    # Assign specific providers/models to agents for multi-model support
    # Uses free tiers where possible (Groq, OpenCode Zen) + user's configured provider
    agent_model_map = {
        # OpenRouter models — requires API key
        "coder":        ("openrouter", "deepseek/deepseek-chat"),
        "debugger":     ("openrouter", "deepseek/deepseek-r1"),
        "security":     ("openrouter", "anthropic/claude-3.5-sonnet"),
        "architect":    ("openrouter", "anthropic/claude-3.5-sonnet"),
        "reviewer":     ("openrouter", "google/gemini-2.0-flash"),
        "db-expert":    ("openrouter", "deepseek/deepseek-chat"),
        "math-solver":  ("openrouter", "deepseek/deepseek-r1"),
        "tutor":        ("openrouter", "google/gemini-2.0-flash"),
        "product-manager": ("openrouter", "anthropic/claude-3.5-sonnet"),
        "ml-engineer":  ("openrouter", "deepseek/deepseek-chat"),
        # OpenCode Zen — free tier, no API key needed
        "writer":         ("opencode", "nemotron-3-ultra-free"),
        "researcher":     ("opencode", "deepseek-v4-flash-free"),
        "creative-writer":("opencode", "big-pickle"),
        "summarizer":     ("opencode", "mimo-v2.5-free"),
        "data-analyst":   ("opencode", "deepseek-v4-flash-free"),
        "devops":         ("opencode", "nemotron-3-ultra-free"),
        "ui-designer":    ("opencode", "big-pickle"),
        "image-gen":      ("opencode", "mimo-v2.5-free"),
        "translator":     ("opencode", "mimo-v2.5-free"),
        "qa-tester":      ("opencode", "nemotron-3-ultra-free"),
        "technical-writer":("opencode", "big-pickle"),
        "game-dev":       ("opencode", "deepseek-v4-flash-free"),
        "mobile-dev":     ("opencode", "nemotron-3-ultra-free"),
        "sys-admin":      ("opencode", "deepseek-v4-flash-free"),
        "network-eng":    ("opencode", "deepseek-v4-flash-free"),
        "cloud-arch":     ("opencode", "big-pickle"),
        "sre":            ("opencode", "nemotron-3-ultra-free"),
        "legal":          ("opencode", "big-pickle"),
        "finance":        ("opencode", "deepseek-v4-flash-free"),
        "data-eng":       ("opencode", "nemotron-3-ultra-free"),
        "blockchain":     ("opencode", "deepseek-v4-flash-free"),
        "cybersec":       ("opencode", "nemotron-3-ultra-free"),
        "gitops":         ("opencode", "deepseek-v4-flash-free"),
        "bioinf":         ("opencode", "big-pickle"),
        "lang-designer":  ("opencode", "mimo-v2.5-free"),
        "robotics":       ("opencode", "deepseek-v4-flash-free"),
        "devex":          ("opencode", "nemotron-3-ultra-free"),
        "opencode":       ("opencode", "big-pickle"),
    }
    for aid, (prov, mdl) in agent_model_map.items():
        conn.execute("UPDATE agents SET provider=?, model=? WHERE id=?", (prov, mdl, aid))
    conn.commit()

    # Set HALO as default active agent
    cur = conn.execute("SELECT value FROM config WHERE key='active_agent'").fetchone()
    if not cur:
        conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('active_agent', 'auto')")
        conn.commit()
    conn.close()

init_db()
seed_default_agents()

def get_config(key: str, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
    conn.close()
    if row:
        try: return json.loads(row["value"])
        except: return row["value"]
    return default

def set_config(key: str, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, json.dumps(value) if not isinstance(value, str) else value))
    conn.commit()
    conn.close()

def load_runtime_state():
    """Load runtime state from DB."""
    state = {}
    provider = get_config("provider")
    if provider: state["provider"] = provider
    model = get_config("model")
    if model: state["model"] = model
    base_url = get_config("base_url")
    if base_url: state["base_url"] = base_url
    keys_raw = get_config("keys", {})
    if isinstance(keys_raw, dict) and keys_raw:
        state["keys"] = keys_raw
    return state

def save_runtime_state(data: dict):
    """Persist runtime state to DB."""
    for k in ("provider", "model", "base_url"):
        if k in data and data[k]:
            set_config(k, data[k])
    if "keys" in data and isinstance(data["keys"], dict):
        existing = get_config("keys", {})
        if isinstance(existing, dict):
            existing.update(data["keys"])
            set_config("keys", existing)

def load_memories():
    conn = get_db()
    rows = conn.execute("SELECT * FROM memories ORDER BY ts DESC").fetchall()
    conn.close()
    result = []
    for r in rows:
        entry = dict(r)
        try: entry["tags"] = json.loads(entry["tags"])
        except: entry["tags"] = []
        try: entry["links"] = json.loads(entry["links"])
        except: entry["links"] = []
        result.append(entry)
    return result

def save_memories(data: list):
    conn = get_db()
    conn.execute("DELETE FROM memories")
    for m in data:
        conn.execute(
            "INSERT OR REPLACE INTO memories (id, text, tags, source, ts, links) VALUES (?, ?, ?, ?, ?, ?)",
            (m["id"], m["text"], json.dumps(m.get("tags", [])), m.get("source", "chat"), m["ts"], json.dumps(m.get("links", [])))
        )
    conn.commit()
    conn.close()

def store_memory(text: str, tags: list = None, source: str = "chat"):
    """Store a memory fragment, auto-link to existing related memories."""
    conn = get_db()
    existing = conn.execute("SELECT id FROM memories WHERE text=?", (text,)).fetchone()
    if existing:
        conn.close()
        return load_memories()
    mem_id = hashlib.md5(text.encode()).hexdigest()[:12]
    timestamp = time.time()
    words = set(w.lower() for w in text.split() if len(w) > 3)
    # find connections
    rows = conn.execute("SELECT id, text, links FROM memories").fetchall()
    links = []
    for r in rows:
        m_words = set(w.lower() for w in r["text"].split() if len(w) > 3)
        overlap = words & m_words
        if len(overlap) >= 2:
            links.append({"target": r["id"], "strength": len(overlap)})
    conn.execute(
        "INSERT INTO memories (id, text, tags, source, ts, links) VALUES (?, ?, ?, ?, ?, ?)",
        (mem_id, text, json.dumps(tags or []), source, timestamp, json.dumps(links[:5]))
    )
    # back-link from targets
    for link in links:
        target_row = conn.execute("SELECT links FROM memories WHERE id=?", (link["target"],)).fetchone()
        if target_row:
            try: target_links = json.loads(target_row["links"])
            except: target_links = []
            if not any(l["target"] == mem_id for l in target_links):
                target_links.append({"target": mem_id, "strength": link["strength"]})
                conn.execute("UPDATE memories SET links=? WHERE id=?", (json.dumps(target_links), link["target"]))
    conn.commit()
    conn.close()
    return load_memories()

def search_memories(query: str, limit: int = 10):
    """Simple keyword-based memory search."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM memories ORDER BY ts DESC").fetchall()
    conn.close()
    words = set(w.lower() for w in query.split() if len(w) > 2)
    scored = []
    for r in rows:
        entry = dict(r)
        try: entry["tags"] = json.loads(entry["tags"])
        except: entry["tags"] = []
        try: entry["links"] = json.loads(entry["links"])
        except: entry["links"] = []
        m_words = set(w.lower() for w in entry["text"].split() if len(w) > 2)
        overlap = words & m_words
        if overlap:
            scored.append((len(overlap), entry))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:limit]]


logging.basicConfig(level=logging.INFO, format="[HALO] %(message)s")
log = logging.getLogger("halo")

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def get_provider_info():
    provider, model, base_url, api_key, state = resolve_active()
    prov = PROVIDERS.get(provider, PROVIDERS["custom"])
    base_url = base_url or prov.get("base_url", "")
    saved_keys = state.get("keys", {})
    return {
        "provider": provider,
        "label": prov["label"],
        "model": model or (prov["models"][0] if prov["models"] else ""),
        "available_models": prov["models"],
        "base_url": base_url,
        "tts_available": TTS_ENABLED and prov["tts"],
        "free_tier": prov["free"],
        "agent": prov.get("agent", False),
        "has_key": bool(api_key),
    }


def serve_file(path: str):
    full = HERE / path.lstrip("/")
    if not full.exists() or not full.is_file():
        full = HERE / "halo_dashboard.html"
    if not full.exists():
        return b"Not Found", "text/plain", 404
    ext = full.suffix
    ctype = MIME.get(ext, "application/octet-stream")
    data = full.read_bytes()
    return data, ctype, 200


def handle(environ, start_response):
    method = environ["REQUEST_METHOD"]
    path = urlparse(environ["PATH_INFO"]).path.rstrip("/") or "/"

    headers = [
        ("Access-Control-Allow-Origin", "*"),
        ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
        ("Access-Control-Allow-Headers", "Content-Type"),
    ]

    if method == "OPTIONS":
        start_response("204 No Content", headers)
        return [b""]

    # ── API: config (GET) ──
    if path == "/api/config" and method == "GET":
        info = get_provider_info()
        _, _, _, api_key, state = resolve_active()
        saved_keys = state.get("keys", {})
        all_providers = {
            k: {
                "label": v["label"],
                "base_url": v["base_url"],
                "has_tts": v["tts"],
                "free": v["free"],
                "has_key": bool(saved_keys.get(k)),
                "models": v["models"],
                "free_models": v.get("free_models", []),
                "agent": v.get("agent", False),
            }
            for k, v in PROVIDERS.items()
        }
        body = json.dumps({
            "active": info,
            "providers": all_providers,
            "tts": {
                "available": TTS_ENABLED,
                "model": TTS_MODEL,
                "voice": TTS_VOICE,
                "edge_available": EDGE_TTS_AVAILABLE,
                "edge_voice": EDGE_TTS_VOICE,
            },
            "has_key": bool(api_key),
            "saved_keys": {k: bool(v) for k, v in saved_keys.items()},
        }).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: save config (POST) — saves key + model + switches ──
    if path == "/api/config/save" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        provider = (data.get("provider") or "").lower().strip()
        if provider not in PROVIDERS:
            body = json.dumps({"error": f"Unknown provider: {provider}"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        # merge with existing state (preserve keys for other providers)
        old_state = load_runtime_state()
        saved_keys = old_state.get("keys", {})

        api_key = (data.get("api_key") or "").strip() if "api_key" in data else ""
        if api_key:
            saved_keys[provider] = api_key
        elif "api_key" in data:
            saved_keys.pop(provider, None)

        new_state = {
            "provider": provider,
            "keys": saved_keys,
        }
        model = (data.get("model") or "").strip()
        if model:
            new_state["model"] = model
        if "model" in old_state and not model:
            new_state["model"] = old_state["model"]

        base_url = (data.get("base_url") or "").strip()
        if base_url:
            new_state["base_url"] = base_url
        elif "base_url" in old_state:
            new_state["base_url"] = old_state["base_url"]

        save_runtime_state(new_state)
        log.info("Config saved — provider: %s  key: %s  model: %s",
                 provider, "saved" if api_key else "unchanged", model or "(default)")

        # re-read to get full resolved info
        info = get_provider_info()
        body = json.dumps({"ok": True, "active": info}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: switch provider (POST, legacy — delegates to save) ──
    if path == "/api/config/switch" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        # delegate to /api/config/save logic
        old_state = load_runtime_state()
        provider = (data.get("provider") or "").lower().strip()
        if provider not in PROVIDERS:
            body = json.dumps({"error": f"Unknown provider: {provider}"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        saved_keys = old_state.get("keys", {})
        new_state = {"provider": provider, "keys": saved_keys}
        model = (data.get("model") or "").strip()
        if model:
            new_state["model"] = model
        elif "model" in old_state:
            new_state["model"] = old_state["model"]
        base_url = (data.get("base_url") or "").strip()
        if base_url:
            new_state["base_url"] = base_url
        elif "base_url" in old_state:
            new_state["base_url"] = old_state["base_url"]

        save_runtime_state(new_state)
        log.info("Switched to provider: %s", provider)

        info = get_provider_info()
        body = json.dumps({"ok": True, "active": info}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: TTS status (legacy) ──
    if path == "/api/tts/status" and method == "GET":
        info = get_provider_info()
        provider, _, _, _, _ = resolve_active()
        body = json.dumps({
            "available": TTS_ENABLED,
            "edge_available": EDGE_TTS_AVAILABLE,
            "edge_voice": EDGE_TTS_VOICE,
            "provider": provider,
            "model": TTS_MODEL,
            "voice": TTS_VOICE,
            "llm_provider": provider,
            "llm_model": info["model"],
        }).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: fetch live models from a provider (LM Studio, Ollama, etc.) ──
    if path == "/api/provider-models" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        provider = (data.get("provider") or "").strip().lower()
        base_url = (data.get("base_url") or "").strip()

        if not base_url and provider in PROVIDERS:
            base_url = PROVIDERS[provider].get("base_url", "")

        if not base_url:
            body = json.dumps({"error": "No base URL for provider", "models": []}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("200 OK", headers)
            return [body]

        try:
            import urllib.request
            api_url = base_url.rstrip("/") + "/models"
            req = urllib.request.Request(api_url, headers={"Accept": "application/json"})
            resp = urllib.request.urlopen(req, timeout=5)
            resp_data = json.loads(resp.read().decode())
            model_list = resp_data.get("data", []) if isinstance(resp_data, dict) else []
            models = [m["id"] for m in model_list if isinstance(m, dict) and m.get("id")]
            body = json.dumps({"ok": True, "provider": provider, "models": models}).encode()
        except Exception as e:
            log.warning("Failed to fetch models from %s: %s", api_url, e)
            body = json.dumps({"error": str(e), "models": []}).encode()

        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: TTS generate ──
    if path == "/api/tts" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        text = data.get("text", "")
        if not text:
            body = json.dumps({"error": "No text"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        # Strategy: try OpenAI TTS → fallback to edge-tts
        if TTS_ENABLED:
            try:
                client = OpenAI(api_key=TTS_API_KEY)
                resp = client.audio.speech.create(
                    model=TTS_MODEL,
                    voice=TTS_VOICE,
                    input=text,
                    response_format="mp3",
                    instructions="Speak in a warm, natural male voice with a calm and confident tone. Vary pitch naturally. Pause at commas and periods. Sound like a helpful human assistant, not a robot.",
                )
                audio = resp.content
                headers.append(("Content-Type", "audio/mpeg"))
                headers.append(("Content-Length", str(len(audio))))
                start_response("200 OK", headers)
                return [audio]
            except Exception as e:
                log.warning("OpenAI TTS failed, falling back to edge-tts: %s", e)

        # edge-tts fallback — free, high quality, no API key needed
        if EDGE_TTS_AVAILABLE:
            try:
                import asyncio
                import edge_tts

                async def _do_edge():
                    communicate = edge_tts.Communicate(text, voice=EDGE_TTS_VOICE, rate="-3%", pitch="+0Hz")
                    chunks = []
                    async for chunk in communicate.stream():
                        if chunk["type"] == "audio":
                            chunks.append(chunk["data"])
                    return b"".join(chunks)

                raw_audio = asyncio.run(_do_edge())
                headers.append(("Content-Type", "audio/mpeg"))
                headers.append(("Content-Length", str(len(raw_audio))))
                start_response("200 OK", headers)
                return [raw_audio]
            except Exception as e:
                log.error("edge-tts error: %s", e)
                body = json.dumps({"error": str(e)}).encode()
                headers.append(("Content-Type", "application/json"))
                start_response("500 Internal Server Error", headers)
                return [body]

        if not TTS_ENABLED and not EDGE_TTS_AVAILABLE:
            body = json.dumps({"error": "No TTS available — add an OpenAI key in Settings or install edge-tts"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("402 Payment Required", headers)
            return [body]

    # ── API: Speech-to-Text (STT) ──
    if path == "/api/stt" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        import base64, io as _io
        audio_b64 = data.get("audio", "")
        if not audio_b64:
            body = json.dumps({"error": "No audio data"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        stt_api_key = TTS_API_KEY or data.get("api_key", "")
        if not stt_api_key:
            body = json.dumps({"error": "No API key for speech recognition"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        try:
            audio_bytes = base64.b64decode(audio_b64)
            sr = data.get("sr", 16000)
            fmt = data.get("format", "webm")
            from openai import OpenAI as _OpenAI
            stt_client = _OpenAI(api_key=stt_api_key)
            import tempfile
            with tempfile.NamedTemporaryFile(suffix="." + fmt, delete=False) as tf:
                tf.write(audio_bytes)
                tf_path = tf.name
            try:
                with open(tf_path, "rb") as af:
                    transcript = stt_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=af,
                        language=data.get("language", "en"),
                    )
                text = transcript.text.strip()
            finally:
                import os as _os
                try: _os.unlink(tf_path)
                except: pass
            body = json.dumps({"ok": True, "text": text}).encode()
        except Exception as e:
            log.error("STT failed: %s", e)
            body = json.dumps({"error": str(e)}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: File System Tools ──
    if path == "/api/tools/read" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        filepath = data.get("path", "").strip()
        if not filepath:
            body = json.dumps({"error": "No path"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        p = Path(filepath).expanduser().resolve()
        if not p.exists():
            body = json.dumps({"error": f"File not found: {p}"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("404 Not Found", headers)
            return [body]
        if p.is_dir():
            files = []
            for f in sorted(p.iterdir()):
                files.append({"name": f.name, "type": "dir" if f.is_dir() else "file", "size": f.stat().st_size if f.is_file() else 0})
            body = json.dumps({"ok": True, "type": "dir", "path": str(p), "files": files}).encode()
        else:
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                content = "(binary file, cannot read as text)"
            body = json.dumps({"ok": True, "type": "file", "path": str(p), "content": content, "size": p.stat().st_size}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/tools/write" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        filepath = data.get("path", "").strip()
        content = data.get("content", "")
        overwrite = data.get("overwrite", True)
        if not filepath:
            body = json.dumps({"error": "No path"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        p = Path(filepath).expanduser().resolve()
        if p.exists() and not overwrite:
            body = json.dumps({"error": "File exists and overwrite=false"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("409 Conflict", headers)
            return [body]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        log.info("Wrote %s (%d bytes)", p, len(content))
        body = json.dumps({"ok": True, "path": str(p), "size": len(content)}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/tools/edit" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        filepath = data.get("path", "").strip()
        old = data.get("old", "")
        new = data.get("new", "")
        if not filepath or not old:
            body = json.dumps({"error": "path and old are required"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        p = Path(filepath).expanduser().resolve()
        if not p.exists():
            body = json.dumps({"error": f"File not found: {p}"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("404 Not Found", headers)
            return [body]
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            body = json.dumps({"error": f"Cannot read file: {e}"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("500 Internal Server Error", headers)
            return [body]
        if old not in content:
            body = json.dumps({"error": "old string not found in file"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        new_content = content.replace(old, new, 1)
        p.write_text(new_content, encoding="utf-8")
        log.info("Edited %s (replaced %d chars)", p, len(old))
        body = json.dumps({"ok": True, "path": str(p), "size": len(new_content)}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/tools/delete" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        filepath = data.get("path", "").strip()
        if not filepath:
            body = json.dumps({"error": "No path"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        p = Path(filepath).expanduser().resolve()
        if not p.exists():
            body = json.dumps({"error": f"Not found: {p}"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("404 Not Found", headers)
            return [body]
        if p.is_dir():
            import shutil
            shutil.rmtree(p)
            log.info("Deleted directory %s", p)
        else:
            p.unlink()
            log.info("Deleted file %s", p)
        body = json.dumps({"ok": True, "path": str(p)}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/tools/mkdir" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        filepath = data.get("path", "").strip()
        if not filepath:
            body = json.dumps({"error": "No path"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        p = Path(filepath).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        log.info("Created directory %s", p)
        body = json.dumps({"ok": True, "path": str(p)}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/tools/run" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        command = data.get("command", "").strip()
        workdir = data.get("workdir", "").strip() or None
        timeout = min(int(data.get("timeout", 30)), 120)
        if not command:
            body = json.dumps({"error": "No command"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        import subprocess
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout, cwd=workdir)
            body = json.dumps({
                "ok": True, "stdout": result.stdout, "stderr": result.stderr,
                "returncode": result.returncode, "command": command
            }).encode()
        except subprocess.TimeoutExpired:
            body = json.dumps({"error": "Command timed out", "command": command}).encode()
            start_response("408 Request Timeout", headers)
            return [body]
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            start_response("500 Internal Server Error", headers)
            return [body]
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: Open file with system default app ──
    if path == "/api/tools/open" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        filepath = data.get("path", "").strip()
        if not filepath:
            body = json.dumps({"error": "No path"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        import subprocess, sys, platform, shutil, re as _re, urllib.parse as _urlparse
        # Check if it's a URL
        if _re.match(r'^https?://', filepath):
            import webbrowser
            webbrowser.open(filepath)
            log.info("Opened URL: %s", filepath)
            body = json.dumps({"ok": True, "path": filepath, "type": "url"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("200 OK", headers)
            return [body]
        p = Path(filepath).expanduser().resolve()
        if not p.exists():
            body = json.dumps({"error": f"Not found: {p}"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("404 Not Found", headers)
            return [body]
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["open", str(p)])
            elif platform.system() == "Windows":
                subprocess.Popen(["start", str(p)], shell=True)
            else:
                # try xdg-open; fallback to exploring file manager for directories
                if p.is_dir():
                    fm = (shutil.which("nautilus") or shutil.which("dolphin") or shutil.which("nemo") or shutil.which("thunar") or shutil.which("pcmanfm"))
                    if fm:
                        subprocess.Popen([fm, str(p)])
                    else:
                        subprocess.Popen(["xdg-open", str(p)])
                else:
                    subprocess.Popen(["xdg-open", str(p)])
            log.info("Opened %s", p)
            body = json.dumps({"ok": True, "path": str(p), "type": "file"}).encode()
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            start_response("500 Internal Server Error", headers)
            return [body]
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: Launch application ──
    if path == "/api/tools/launch" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        app_name = data.get("app", "").strip()
        args = data.get("args", "")
        if not app_name:
            body = json.dumps({"error": "No app name"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        import subprocess, shutil, platform, glob as _glob, os as _os
        errors = []
        def _try_launch(cmd, desc):
            try:
                if platform.system() == "Windows":
                    subprocess.Popen(cmd if isinstance(cmd, str) else " ".join(cmd), shell=True)
                else:
                    subprocess.Popen(cmd)
                log.info("Launched %s via %s", app_name, desc)
                return True
            except Exception as e:
                errors.append(f"{desc}: {e}")
                return False
        launched = False
        if platform.system() == "Darwin":
            launched = _try_launch(["open", "-a", app_name] + ([args] if args else []), "open -a")
        elif platform.system() == "Windows":
            launched = _try_launch(f'start "" "{app_name}" {args}', "start")
        else:
            # Strategy 1: direct binary in PATH
            which = shutil.which(app_name)
            if which:
                launched = _try_launch([which] + ([args] if args else []), "PATH binary")
            if not launched:
                desktop = app_name if app_name.endswith(".desktop") else app_name + ".desktop"
                desktop_paths = _glob.glob(f"/usr/share/applications/{desktop}") + _glob.glob(f"/usr/local/share/applications/{desktop}") + _glob.glob(f"{_os.path.expanduser('~')}/.local/share/applications/{desktop}")
                if not desktop_paths:
                    # fuzzy match: try to find a .desktop file containing the app name
                    all_desktop = _glob.glob("/usr/share/applications/*.desktop") + _glob.glob("/usr/local/share/applications/*.desktop") + _glob.glob(f"{_os.path.expanduser('~')}/.local/share/applications/*.desktop")
                    for dp in all_desktop:
                        base = _os.path.basename(dp).replace(".desktop", "").lower()
                        if app_name.lower() in base:
                            desktop_paths = [dp]
                            break
                if desktop_paths:
                    launched = _try_launch(["gtk-launch", _os.path.basename(desktop_paths[0]).replace(".desktop", "")], "gtk-launch desktop")
            if not launched:
                launched = _try_launch(["xdg-open", app_name], "xdg-open")
            if not launched:
                launched = _try_launch([app_name] + ([args] if args else []), "direct")
        if launched:
            body = json.dumps({"ok": True, "app": app_name}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("200 OK", headers)
            return [body]
        else:
            body = json.dumps({"error": f"Could not launch \"{app_name}\"", "details": errors}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("404 Not Found", headers)
            return [body]

    # ── API: List available applications ──
    if path == "/api/tools/apps" and method == "GET":
        import glob as _glob, os as _os
        apps = []
        seen = set()
        for base_dir in ["/usr/share/applications", "/usr/local/share/applications", _os.path.expanduser("~/.local/share/applications")]:
            for f in _glob.glob(f"{base_dir}/*.desktop"):
                try:
                    name = None
                    exec_cmd = None
                    icon = None
                    for line in open(f, "r", encoding="utf-8", errors="replace"):
                        if line.startswith("Name=") and not name:
                            name = line.split("=", 1)[1].strip()
                        elif line.startswith("Exec="):
                            exec_cmd = line.split("=", 1)[1].strip()
                        elif line.startswith("Icon="):
                            icon = line.split("=", 1)[1].strip()
                    if name and name not in seen:
                        seen.add(name)
                        apps.append({
                            "name": name,
                            "desktop": _os.path.basename(f).replace(".desktop", ""),
                            "exec": exec_cmd,
                            "icon": icon,
                            "path": f,
                        })
                except Exception:
                    pass
        apps.sort(key=lambda x: x["name"].lower())
        body = json.dumps({"ok": True, "apps": apps}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: Install package ──
    if path == "/api/tools/install" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        pkg = data.get("package", "").strip()
        manager = data.get("manager", "").strip().lower() or "auto"
        if not pkg:
            body = json.dumps({"error": "No package name"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        import subprocess, shutil
        if manager == "auto":
            if shutil.which("apt-get"):
                manager = "apt"
            elif shutil.which("brew"):
                manager = "brew"
            elif shutil.which("pip3"):
                manager = "pip"
            elif shutil.which("npm"):
                manager = "npm"
            else:
                body = json.dumps({"error": "No package manager detected (apt/brew/pip/npm)", "manager": manager}).encode()
                headers.append(("Content-Type", "application/json"))
                start_response("400 Bad Request", headers)
                return [body]
        manager_map = {
            "apt":   ["apt-get", "install", "-y"],
            "brew":  ["brew", "install"],
            "pip":   ["pip3", "install"],
            "npm":   ["npm", "install", "-g"],
            "snap":  ["snap", "install"],
        }
        if manager not in manager_map:
            body = json.dumps({"error": f"Unsupported package manager: {manager}", "supported": list(manager_map.keys())}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        try:
            cmd = manager_map[manager] + [pkg]
            log.info("Installing package: %s via %s", pkg, manager)
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            body = json.dumps({
                "ok": True, "package": pkg, "manager": manager,
                "stdout": result.stdout[-2000:],
                "stderr": result.stderr[-2000:],
                "returncode": result.returncode
            }).encode()
        except subprocess.TimeoutExpired:
            body = json.dumps({"error": "Install timed out (120s)", "package": pkg}).encode()
            start_response("408 Request Timeout", headers)
            return [body]
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            start_response("500 Internal Server Error", headers)
            return [body]
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: System info ──
    if path == "/api/tools/system" and method == "GET":
        import shutil, platform
        info = {
            "os": platform.system() + " " + platform.release(),
            "hostname": platform.node(),
            "python": platform.python_version(),
        }
        try:
            import psutil
            info["cpu"] = {"count": psutil.cpu_count(), "percent": psutil.cpu_percent(interval=0.1)}
            info["memory"] = {"total": psutil.virtual_memory().total, "available": psutil.virtual_memory().available, "percent": psutil.virtual_memory().percent}
        except ImportError:
            info["cpu"] = {"note": "Install psutil for CPU/memory details"}
        try:
            du = shutil.disk_usage("/")
            info["disk"] = {"total": du.total, "free": du.free, "used": du.used, "percent": round(100 - (du.free / du.total * 100), 1)}
        except Exception:
            info["disk"] = {"note": "Disk info unavailable"}
        body = json.dumps({"ok": True, "system": info}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: File search ──
    if path == "/api/tools/find" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        pattern = data.get("pattern", "").strip()
        root = data.get("root", "/").strip() or "/"
        max_results = min(int(data.get("max", 50)), 200)
        if not pattern:
            body = json.dumps({"error": "No pattern"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        import glob as gmod
        results = []
        try:
            for p in gmod.iglob(os.path.join(root, pattern), recursive=True):
                if len(results) >= max_results:
                    break
                try:
                    sp = Path(p)
                    results.append({"path": str(sp), "type": "dir" if sp.is_dir() else "file", "size": sp.stat().st_size if sp.is_file() else 0})
                except Exception:
                    pass
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode()
            start_response("500 Internal Server Error", headers)
            return [body]
        body = json.dumps({"ok": True, "results": results, "total": len(results)}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: Agents CRUD ──
    if path == "/api/agents" and method == "GET":
        conn = get_db()
        rows = conn.execute("SELECT * FROM agents ORDER BY created_at ASC").fetchall()
        conn.close()
        agents = [dict(r) for r in rows]
        active = get_config("active_agent", "auto")
        body = json.dumps({"agents": agents, "active": active}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/agents" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        import uuid
        aid = data.get("id", uuid.uuid4().hex[:8])
        name = data.get("name", "").strip()
        if not name:
            body = json.dumps({"error": "Name required"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO agents (id,name,role,icon,provider,model,system_prompt,skills,tools,temperature,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (aid, name, data.get("role", ""), data.get("icon", "🤖"),
             data.get("provider", ""), data.get("model", ""),
             data.get("system_prompt", ""),
             json.dumps(data.get("skills", [])), json.dumps(data.get("tools", [])),
             float(data.get("temperature", 0.7)), time.time()),
        )
        conn.commit()
        # Set as active if first agent or explicitly requested
        if data.get("activate", False):
            set_config("active_agent", aid)
        conn.close()
        body = json.dumps({"ok": True, "id": aid}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/agents/activate" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        aid = data.get("id", "")
        conn = get_db()
        row = conn.execute("SELECT id FROM agents WHERE id=?", (aid,)).fetchone()
        conn.close()
        if not row:
            body = json.dumps({"error": "Agent not found"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("404 Not Found", headers)
            return [body]
        set_config("active_agent", aid)
        body = json.dumps({"ok": True, "active": aid}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/agents/delete" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        aid = data.get("id", "")
        conn = get_db()
        conn.execute("DELETE FROM agents WHERE id=?", (aid,))
        conn.commit()
        conn.close()
        # Reset active agent if deleted
        if get_config("active_agent") == aid:
            set_config("active_agent", "halo")
        body = json.dumps({"ok": True}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: Chat (LLM with skills/tools/memory/file-system integration) ──
    if path == "/api/chat" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        message = data.get("message", "").strip()
        history = data.get("history", [])
        enabled_skills = data.get("skills", [])
        enabled_tools = data.get("tools", [])
        agent_enabled = data.get("agent", True)
        agent_id = data.get("agent_id", "")
        language = data.get("language", "English")

        if not message:
            body = json.dumps({"error": "No message"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        # Load agent config or auto-route
        active_agent = None
        conn = get_db()
        all_agents = [dict(r) for r in conn.execute("SELECT * FROM agents").fetchall()]
        conn.close()

        # Resolve active provider first (needed for routing)
        provider, model, base_url, api_key, state = resolve_active()
        prov_config = PROVIDERS.get(provider, PROVIDERS["custom"])
        base_url = base_url or prov_config.get("base_url", "")

        should_route = (not agent_id or agent_id == "auto")

        if should_route:
            routed_id = _route_to_agent(message, all_agents)
            if routed_id:
                agent_id = routed_id

        if agent_id and agent_id != "auto":
            conn = get_db()
            row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
            conn.close()
            if row:
                active_agent = dict(row)

        if not active_agent:
            conn = get_db()
            row = conn.execute("SELECT * FROM agents WHERE id='halo'").fetchone()
            conn.close()
            if row:
                active_agent = dict(row)

        # Apply agent-level provider/model override
        if active_agent and active_agent.get("provider"):
            provider, model, base_url, api_key, state = resolve_active(provider_override=active_agent["provider"])
            prov_config = PROVIDERS.get(active_agent["provider"], prov_config)
            base_url = base_url or prov_config.get("base_url", "")
        if active_agent and active_agent.get("model"):
            model = active_agent["model"]

        if not api_key and provider not in ("ollama", "lmstudio", "custom", "opencode"):
            body = json.dumps({"error": f"No API key configured for {prov_config['label']}"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        # Merge agent skills/tools with user-provided ones
        if active_agent:
            try:
                agent_skills = json.loads(active_agent.get("skills", "[]"))
                if agent_skills and not enabled_skills:
                    enabled_skills = agent_skills
            except: pass
            try:
                agent_tools = json.loads(active_agent.get("tools", "[]"))
                if agent_tools and not enabled_tools:
                    enabled_tools = agent_tools
            except: pass

        # Recall relevant memories
        memories = search_memories(message, limit=5)

        # Process attached files
        files = data.get("files", [])
        file_context = ""
        if files:
            import base64
            file_parts = []
            for f in files:
                name = f.get("name", "unknown")
                ftype = f.get("type", "")
                size = f.get("size", 0)
                data_url = f.get("data", "")
                # Check if it's a text file by extension
                text_exts = {'.txt', '.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.json', '.md', '.csv', '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf', '.sh', '.bash', '.zsh', '.bat', '.ps1', '.rb', '.go', '.rs', '.java', '.cpp', '.c', '.h', '.hpp', '.php', '.sql', '.r', '.m', '.swift', '.kt', '.scala', '.pl', '.lua', '.groovy', '.gradle', '.env', '.gitignore', '.dockerfile', '.makefile', '.cfg', '.log', '.tex', '.rst', '.cfg'}
                ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if ext in text_exts or ftype.startswith("text/"):
                    try:
                        b64 = data_url.split(",", 1)[-1] if "," in data_url else data_url
                        decoded = base64.b64decode(b64).decode("utf-8", errors="replace")
                        file_parts.append(f"--- File: {name} ---\n{decoded}\n--- End {name} ---")
                    except Exception:
                        file_parts.append(f"[File: {name} ({size} bytes, type: {ftype}) — could not decode as text]")
                elif ftype.startswith("image/"):
                    file_parts.append(f"[Image: {name} ({size} bytes)]")
                else:
                    file_parts.append(f"[File: {name} ({size} bytes, type: {ftype})]")
            if file_parts:
                file_context = "\n\n".join(file_parts)

        # Build system prompt
        skill_desc = {
            "code": "Execute Python/shell code",
            "web": "Search the web and fetch content",
            "files": "Read/write/delete files",
            "memory": "Recall from Memory Vault knowledge graph",
            "ui-ux": "Design UI/UX with Figma, wireframes, mockups",
            "css": "CSS art, animations, glassmorphism, visual effects",
            "data-viz": "Charts, graphs, data visualizations",
            "debug": "Troubleshoot errors and fix bugs",
            "refactor": "Restructure code for maintainability",
            "docs": "Write and format documentation",
            "test": "Unit, integration, and e2e testing",
            "security": "Audit code for vulnerabilities",
            "perf": "Optimize performance and memory",
            "api-design": "Design REST/GraphQL APIs",
            "accessibility": "WCAG and ARIA compliance",
            "responsive": "Mobile-first responsive layouts",
        }
        tool_desc = {
            "web-fetch": "Fetch any URL",
            "code-run": "Execute Python in sandbox",
            "file-edit": "Read/write/delete files",
            "terminal": "Run shell commands",
            "database": "Query databases with SQL",
            "image-gen": "Generate images (DALL·E / SD)",
            "api-tester": "Test REST APIs",
            "git": "Git operations (commit, push, pull)",
            "deploy": "Deploy to production",
            "docker": "Manage Docker containers",
            "search": "Web search",
            "translate": "Translate between 50+ languages",
            "summarize": "Summarize long text",
            "screenshot": "Capture web page screenshots",
            "pdf-reader": "Extract text from PDFs",
            "desktop": "Open files with system default applications",
            "app-launcher": "Launch installed applications by name",
            "system-info": "Get OS, CPU, memory, disk information",
            "file-finder": "Search filesystem by glob pattern",
        }

        skills_str = ", ".join(enabled_skills) if enabled_skills else "none"
        tools_str = ", ".join(enabled_tools) if enabled_tools else "none"

        lines = []
        if active_agent and active_agent.get("system_prompt"):
            lines.append(active_agent["system_prompt"])
            lines.append("")
        lines.append(f"You are acting as {active_agent['name'] if active_agent else 'H.A.L.O.'} ({active_agent['role'] if active_agent else 'General AI assistant'}), running on {prov_config['label']} ({model or 'default'}).")
        lines.append(f"Available skills: {skills_str}")
        lines.append(f"Available tools: {tools_str}")
        lines.append(f"Agent mode: {'ON — you may use tools autonomously' if agent_enabled else 'OFF — chat only'}")
        lines.append("")
        lines.append("Guidelines:")
        lines.append("- Be concise and natural. Don't list your capabilities unless asked.")
        lines.append("- Use tools/skills when relevant to complete the user's request.")
        lines.append("- When agent mode is ON, you can decide which tools to use.")
        lines.append("- When agent mode is OFF, respond conversationally only.")
        lines.append("- If you need more information, ask the user.")
        lines.append(f"- IMPORTANT: Always respond in {language}. Use {language} for all replies.")

        if agent_enabled:
            lines.extend([
                "",
                "You have FULL filesystem access. Use these tools when needed:",
                "- write_file(path, content) — create/overwrite files (creates parent dirs)",
                "- read_file(path) — read files or list directories",
                "- edit_file(path, old, new) — edit files by replacing text",
                "- delete_file(path) — delete files or directories",
                "- open_file(path) — open a file with the system default application",
                "- launch_app(app, args) — launch an installed application by name",
                "- system_info() — get OS, CPU, memory, disk information",
                "- find_files(pattern, root, max) — search filesystem by glob pattern (e.g. **/*.txt)",
                "- create_directory(path) — create folders",
                "- run_command(command, workdir, timeout) — execute shell commands",
                "",
                "To invoke a tool, wrap JSON in a tool code block:",
                '```tool',
                '{"name": "write_file", "args": {"path": "...", "content": "..."}}',
                '```',
                "Rules:",
                "1. Use tools freely — don't ask for permission.",
                "2. You can include MULTIPLE tool blocks in one response.",
                "3. After all tools execute, you'll get results. Then respond to the user.",
                "4. Never output tool blocks after seeing results — just reply in text.",
            ])

        system_prompt = "\n".join(lines)

        # Build conversation messages
        messages = [{"role": "system", "content": system_prompt}]

        # Add history (last 10 messages max)
        for h in history[-10:]:
            role = "user" if h.get("role") == "user" else "assistant"
            messages.append({"role": role, "content": h.get("content", "")})

        user_content = message
        if file_context:
            user_content = file_context + "\n\n" + message
        messages.append({"role": "user", "content": user_content})

        # Tool name mapping (for reference and direct execution)
        tool_map = {
            "read_file": "/api/tools/read",
            "write_file": "/api/tools/write",
            "edit_file": "/api/tools/edit",
            "delete_file": "/api/tools/delete",
            "create_directory": "/api/tools/mkdir",
            "run_command": "/api/tools/run",
            "open_file": "/api/tools/open",
            "launch_app": "/api/tools/launch",
            "system_info": "/api/tools/system",
            "find_files": "/api/tools/find",
        }

        def _call_tool_api(name: str, args: dict) -> dict:
            """Execute a tool directly (no HTTP — avoids WSGI deadlock)."""
            try:
                from pathlib import Path
                filepath = args.get("path", "").strip() if "path" in args else ""
                if name == "read_file":
                    p = Path(filepath).expanduser().resolve()
                    if not p.exists():
                        return {"error": "Not found"}
                    if p.is_dir():
                        return {"files": [str(f.relative_to(p)) for f in p.iterdir()]}
                    return {"content": p.read_text(encoding="utf-8")}
                elif name == "write_file":
                    content = args.get("content", "")
                    p = Path(filepath).expanduser().resolve()
                    p.parent.mkdir(parents=True, exist_ok=True)
                    overwrite = args.get("overwrite", True)
                    if p.exists() and not overwrite:
                        return {"error": "File exists"}
                    p.write_text(content, encoding="utf-8")
                    return {"ok": True, "path": str(p), "size": len(content)}
                elif name == "edit_file":
                    old = args.get("old", "")
                    new = args.get("new", "")
                    if not filepath or not old:
                        return {"error": "path and old required"}
                    p = Path(filepath).expanduser().resolve()
                    if not p.exists():
                        return {"error": "Not found"}
                    text = p.read_text(encoding="utf-8")
                    if old not in text:
                        return {"error": "String not found"}
                    p.write_text(text.replace(old, new), encoding="utf-8")
                    return {"ok": True, "path": str(p)}
                elif name == "delete_file":
                    p = Path(filepath).expanduser().resolve()
                    if not p.exists():
                        return {"error": "Not found"}
                    if p.is_dir():
                        import shutil
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                    return {"ok": True, "path": str(p)}
                elif name == "create_directory":
                    p = Path(filepath).expanduser().resolve()
                    p.mkdir(parents=True, exist_ok=True)
                    return {"ok": True, "path": str(p)}
                elif name == "run_command":
                    import subprocess
                    cmd = args.get("command", "")
                    workdir = args.get("workdir", None)
                    timeout = args.get("timeout", 30)
                    if not cmd:
                        return {"error": "No command"}
                    result = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True,
                        cwd=workdir, timeout=timeout,
                    )
                    return {
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                        "returncode": result.returncode,
                    }
                elif name == "open_file":
                    import subprocess, platform, re as _re, shutil
                    fp = args.get("path", "")
                    if _re.match(r'^https?://', fp):
                        import webbrowser
                        webbrowser.open(fp)
                        return {"ok": True, "path": fp, "type": "url"}
                    p = Path(fp).expanduser().resolve()
                    if not p.exists():
                        return {"error": f"Not found: {p}"}
                    if platform.system() == "Darwin":
                        subprocess.Popen(["open", str(p)])
                    elif platform.system() == "Windows":
                        subprocess.Popen(["start", str(p)], shell=True)
                    else:
                        if p.is_dir():
                            fm = (shutil.which("nautilus") or shutil.which("dolphin") or shutil.which("nemo") or shutil.which("thunar") or shutil.which("pcmanfm"))
                            if fm:
                                subprocess.Popen([fm, str(p)])
                            else:
                                subprocess.Popen(["xdg-open", str(p)])
                        else:
                            subprocess.Popen(["xdg-open", str(p)])
                    return {"ok": True, "path": str(p)}
                elif name == "launch_app":
                    import subprocess, shutil, platform, glob as _glob, os as _os
                    app = args.get("app", "")
                    app_args = args.get("args", "")
                    if not app:
                        return {"error": "No app"}
                    errors = []
                    def _try(cmd, desc):
                        try:
                            if platform.system() == "Windows":
                                subprocess.Popen(cmd if isinstance(cmd, str) else " ".join(cmd), shell=True)
                            else:
                                subprocess.Popen(cmd)
                            return True
                        except Exception as e:
                            errors.append(f"{desc}: {e}")
                            return False
                    launched = False
                    if platform.system() == "Darwin":
                        launched = _try(["open", "-a", app] + ([app_args] if app_args else []), "open -a")
                    elif platform.system() == "Windows":
                        launched = _try(f'start "" "{app}" {app_args}', "start")
                    else:
                        which = shutil.which(app)
                        if which:
                            launched = _try([which] + ([app_args] if app_args else []), "PATH binary")
                        if not launched:
                            desktop = app if app.endswith(".desktop") else app + ".desktop"
                            desk_paths = _glob.glob(f"/usr/share/applications/{desktop}") + _glob.glob(f"/usr/local/share/applications/{desktop}") + _glob.glob(f"{_os.path.expanduser('~')}/.local/share/applications/{desktop}")
                            if not desk_paths:
                                all_desk = _glob.glob("/usr/share/applications/*.desktop") + _glob.glob("/usr/local/share/applications/*.desktop") + _glob.glob(f"{_os.path.expanduser('~')}/.local/share/applications/*.desktop")
                                for dp in all_desk:
                                    if app.lower() in _os.path.basename(dp).replace(".desktop", "").lower():
                                        desk_paths = [dp]
                                        break
                            if desk_paths:
                                launched = _try(["gtk-launch", _os.path.basename(desk_paths[0]).replace(".desktop", "")], "gtk-launch desktop")
                        if not launched:
                            launched = _try(["xdg-open", app], "xdg-open")
                        if not launched:
                            launched = _try([app] + ([app_args] if app_args else []), "direct")
                    if launched:
                        return {"ok": True, "app": app}
                    return {"error": f"Could not launch \"{app}\"", "details": errors}
                elif name == "system_info":
                    try:
                        import psutil
                        info = {
                            "os": platform.system() + " " + platform.release(),
                            "cpu_count": psutil.cpu_count(),
                            "cpu_percent": psutil.cpu_percent(interval=0.1),
                            "memory_total": psutil.virtual_memory().total,
                            "memory_available": psutil.virtual_memory().available,
                            "memory_percent": psutil.virtual_memory().percent,
                        }
                    except ImportError:
                        info = {"os": platform.system() + " " + platform.release(), "cpu_count": "N/A (psutil not installed)"}
                    return {"info": info}
                elif name == "find_files":
                    import glob as gmod
                    pattern = args.get("pattern", "")
                    root = args.get("root", "/")
                    max_results = min(int(args.get("max", 50)), 200)
                    if not pattern:
                        return {"error": "No pattern"}
                    results = []
                    for p in gmod.iglob(os.path.join(root, pattern), recursive=True):
                        if len(results) >= max_results:
                            break
                        try:
                            sp = Path(p)
                            results.append({"path": str(sp), "type": "dir" if sp.is_dir() else "file", "size": sp.stat().st_size if sp.is_file() else 0})
                        except Exception:
                            pass
                    return {"results": results, "total": len(results)}
                return {"error": f"Unknown tool: {name}"}
            except Exception as e:
                return {"error": str(e)}

        def _extract_tool_blocks(text: str) -> list:
            """Extract ```tool ... ``` blocks from AI response."""
            import re
            blocks = []
            for match in re.finditer(r'```tool\s*\n(.*?)\n```', text, re.DOTALL):
                try:
                    data = json.loads(match.group(1).strip())
                    if isinstance(data, dict) and "name" in data and "args" in data:
                        blocks.append(data)
                except Exception:
                    pass
            return blocks

        # Call LLM (without native function calling — use prompt-based tool invocation)
        try:
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=60.0)
            model_name = model or prov_config["models"][0]

            # Make the initial call
            agent_temp = 0.7
            if active_agent and active_agent.get("temperature"):
                try: agent_temp = float(active_agent["temperature"])
                except: pass
            resp = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=agent_temp,
                max_tokens=4096,
            )

            reply = resp.choices[0].message.content or ""
            log.info("AI initial response (first 200 chars): %s", reply[:200])

            # Tool execution loop — parse and execute tool blocks, feed results back
            max_tool_rounds = 8
            tool_round = 0
            final_reply = reply

            while tool_round < max_tool_rounds:
                tool_blocks = _extract_tool_blocks(reply)
                if not tool_blocks:
                    break

                tool_round += 1

                # Execute each tool and collect results
                tool_results = []
                for tb in tool_blocks:
                    name = tb.get("name", "")
                    args = tb.get("args", {})
                    log.info("Executing tool: %s with args: %s", name, json.dumps(args))
                    result = _call_tool_api(name, args)
                    log.info("Tool result: %s", json.dumps(result)[:200])
                    tool_results.append(f"Tool {name} result: {json.dumps(result)}")

                # Strip tool blocks from the visible reply
                import re
                clean_reply = re.sub(r'```tool\s*\n.*?\n```', '', reply, flags=re.DOTALL).strip()
                if not clean_reply:
                    clean_reply = f"I am executing the requested tool operation to fulfill the user's request."

                # Add assistant's response to conversation
                messages.append({"role": "assistant", "content": clean_reply})

                # Feed results back — tell the model to STOP using tools and respond
                messages.append({"role": "user", "content": "Tool results:\n" + "\n".join(tool_results) + "\n\nTask completed. Now respond to the user's ORIGINAL request with the final result. DO NOT use any more tool blocks."})

                # Next LLM call
                log.info("Making follow-up LLM call (tool round %d)...", tool_round)
                resp = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=0.3,  # lower temperature = more deterministic
                    max_tokens=4096,
                )
                reply = resp.choices[0].message.content or ""

                # If no more tool blocks, this is the final reply
                if not _extract_tool_blocks(reply):
                    final_reply = reply
                    break
            else:
                # Reached max rounds — use last reply
                final_reply = reply

        except Exception as e:
            log.error("LLM call failed: %s", e)
            body = json.dumps({"error": str(e)}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("500 Internal Server Error", headers)
            return [body]

        # Strip any inline JSON tool calls that leaked into the final reply
        import re as _re
        final_reply = _re.sub(
            r'\{"name"\s*:\s*"[^"]*"\s*,\s*"args"\s*:\s*\{[^}]*\}\s*\}',
            '', final_reply
        ).strip()
        # Also strip ```tool blocks that somehow survived
        final_reply = _re.sub(r'```tool\s*\n.*?\n```', '', final_reply, flags=_re.DOTALL).strip()
        # Clean up leading/trailing punctuation if removal made a mess
        final_reply = _re.sub(r'^[,.\s;:]+|[,.\s;:]+$', '', final_reply).strip()

        # Store memory
        store_memory(final_reply, tags=[], source="assistant")
        store_memory(message, tags=[], source="user")

        body = json.dumps({"reply": final_reply, "agent": active_agent}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: Memory Vault ──
    if path == "/api/memory/graph" and method == "GET":
        memories = load_memories()
        nodes = [{"id": m["id"], "text": m["text"][:80], "tags": m["tags"], "source": m["source"], "ts": m["ts"]} for m in memories]
        edges = []
        for m in memories:
            for link in m.get("links", []):
                edges.append({"source": m["id"], "target": link["target"], "strength": link["strength"]})
        body = json.dumps({"nodes": nodes, "edges": edges, "total": len(memories)}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/memory/store" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        text = data.get("text", "").strip()
        if not text:
            body = json.dumps({"error": "No text"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        tags = data.get("tags", [])
        source = data.get("source", "chat")
        result = store_memory(text, tags, source)
        body = json.dumps({"ok": True, "total": len(result)}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/memory/search" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        query = data.get("query", "").strip()
        if not query:
            body = json.dumps({"error": "No query"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        results = search_memories(query)
        body = json.dumps({"results": results}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/memory/recall" and method == "POST":
        """AI calls this to recall relevant memories before generating a response."""
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        context = data.get("context", "").strip()
        if not context:
            body = json.dumps({"results": []}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("200 OK", headers)
            return [body]
        results = search_memories(context, limit=5)
        # also return recent memories for general awareness
        memories = load_memories()
        recent = sorted(memories, key=lambda m: -m["ts"])[:3]
        # merge dedup
        seen = set(r["id"] for r in results)
        for r in recent:
            if r["id"] not in seen:
                results.append(r)
                seen.add(r["id"])
        body = json.dumps({"results": results}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: Memory delete ──
    if path == "/api/memory/delete" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        mem_id = data.get("id", "").strip()
        if not mem_id:
            body = json.dumps({"error": "No id"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        conn = get_db()
        conn.execute("DELETE FROM memories WHERE id=?", (mem_id,))
        # clean up links pointing to deleted memory
        rows = conn.execute("SELECT id, links FROM memories").fetchall()
        for r in rows:
            try: links = json.loads(r["links"])
            except: links = []
            before = len(links)
            links = [l for l in links if l.get("target") != mem_id]
            if len(links) != before:
                conn.execute("UPDATE memories SET links=? WHERE id=?", (json.dumps(links), r["id"]))
        conn.commit()
        conn.close()
        body = json.dumps({"ok": True}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: Memory update (text, tags) ──
    if path == "/api/memory/update" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        mem_id = data.get("id", "").strip()
        if not mem_id:
            body = json.dumps({"error": "No id"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]
        conn = get_db()
        existing = conn.execute("SELECT * FROM memories WHERE id=?", (mem_id,)).fetchone()
        if not existing:
            conn.close()
            body = json.dumps({"error": "Not found"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("404 Not Found", headers)
            return [body]
        text = data.get("text")
        tags = data.get("tags")
        if text is not None:
            conn.execute("UPDATE memories SET text=? WHERE id=?", (text, mem_id))
        if tags is not None:
            conn.execute("UPDATE memories SET tags=? WHERE id=?", (json.dumps(tags), mem_id))
        conn.commit()
        conn.close()
        body = json.dumps({"ok": True}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: MCP list (GET) + toggle (POST) ──
    if path == "/api/mcp" and method == "GET":
        body = json.dumps({"servers": MCP_SERVERS}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    # ── API: Conversations (per-agent history) ──
    if path == "/api/conversations" and method == "GET":
        conn = get_db()
        rows = conn.execute("SELECT agent_id, messages, updated_at FROM conversations ORDER BY updated_at DESC").fetchall()
        conn.close()
        result = {}
        for r in rows:
            try: msgs = json.loads(r["messages"])
            except: msgs = []
            result[r["agent_id"]] = {"messages": msgs, "updated_at": r["updated_at"]}
        body = json.dumps(result).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/conversations/save" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        agent_id = (data.get("agent_id") or "").strip()
        messages = data.get("messages", [])
        if not agent_id:
            body = json.dumps({"error": "agent_id required"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        conn = get_db()
        conn.execute(
            "INSERT OR REPLACE INTO conversations (agent_id, messages, updated_at) VALUES (?, ?, ?)",
            (agent_id, json.dumps(messages), time.time())
        )
        conn.commit()
        conn.close()
        body = json.dumps({"ok": True}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("200 OK", headers)
        return [body]

    if path == "/api/mcp/toggle" and method == "POST":
        try:
            length = int(environ.get("CONTENT_LENGTH", "0"))
            raw = environ["wsgi.input"].read(length)
            data = json.loads(raw)
        except Exception:
            body = json.dumps({"error": "Bad request"}).encode()
            headers.append(("Content-Type", "application/json"))
            start_response("400 Bad Request", headers)
            return [body]

        mcp_id = (data.get("id") or "").strip()
        enabled = data.get("enabled", True)
        for srv in MCP_SERVERS:
            if srv["id"] == mcp_id:
                srv["enabled"] = enabled
                log.info("MCP %s → %s", mcp_id, "enabled" if enabled else "disabled")
                body = json.dumps({"ok": True, "server": srv}).encode()
                headers.append(("Content-Type", "application/json"))
                start_response("200 OK", headers)
                return [body]

        body = json.dumps({"error": f"MCP server '{mcp_id}' not found"}).encode()
        headers.append(("Content-Type", "application/json"))
        start_response("404 Not Found", headers)
        return [body]

    # ── Static files ──
    data, ctype, status = serve_file(path)
    headers.append(("Content-Type", ctype))
    headers.append(("Cache-Control", "no-cache, no-store, must-revalidate"))
    headers.append(("Pragma", "no-cache"))
    headers.append(("Expires", "0"))
    start_response(f"{status} OK" if status == 200 else f"{status} Not Found", headers)
    return [data]


if __name__ == "__main__":
    from wsgiref.simple_server import make_server
    info = get_provider_info()
    _, _, base_url, api_key, _ = resolve_active()
    log.info("H.A.L.O. server on http://127.0.0.1:%s", PORT)
    log.info("Provider: %s | Model: %s | Key: %s", info["label"], info["model"], "yes" if api_key else "no")
    log.info("Database: %s", DB_PATH)
    tts_modes = "+".join(filter(None, [
        "OpenAI" if TTS_ENABLED else "",
        "edge-tts" if EDGE_TTS_AVAILABLE else "",
        "browser" if not TTS_ENABLED and not EDGE_TTS_AVAILABLE else "",
    ])) or "none"
    log.info("TTS: %s (voice: %s, model: %s, edge: %s)", tts_modes, TTS_VOICE, TTS_MODEL, EDGE_TTS_VOICE)
    if base_url:
        log.info("Base URL: %s", base_url)
    httpd = make_server("127.0.0.1", PORT, handle)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("Shutdown.")
