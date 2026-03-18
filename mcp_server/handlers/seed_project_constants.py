"""Constants for the seed_project discovery stages.

Heat values, config file names, doc globs, entry points, CI/CD files,
ignored directories, and language extension mappings.
"""

from __future__ import annotations

HEAT_BY_TYPE = {
    "structural_summary": 0.9,
    "documentation": 0.85,
    "entry_point": 0.80,
    "config": 0.70,
    "ci_cd": 0.60,
}

CONFIG_FILES = [
    "package.json",
    "package-lock.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "pom.xml",
    "build.gradle",
    "composer.json",
    ".ruby-version",
    "Gemfile",
    "mix.exs",
]

DOC_GLOBS = ["README*", "CLAUDE*", "CONTRIBUTING*", "CHANGELOG*", "ARCHITECTURE*"]
DOC_DIRS = ["docs", "doc", "documentation", "adr", "docs/adr"]

ENTRY_POINT_NAMES = {
    "__main__.py",
    "main.py",
    "app.py",
    "server.py",
    "cli.py",
    "index.js",
    "index.ts",
    "main.js",
    "main.ts",
    "server.js",
    "main.go",
    "cmd/main.go",
    "main.rs",
    "src/main.rs",
    "Main.java",
}

CI_FILES = [
    ".github/workflows",
    "Makefile",
    "makefile",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "tox.ini",
    ".travis.yml",
    "circle.yml",
    ".circleci",
    "Jenkinsfile",
    ".gitlab-ci.yml",
    "bitbucket-pipelines.yml",
]

IGNORE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    "target",
    "out",
    ".next",
    ".nuxt",
    "coverage",
    ".coverage",
    "htmlcov",
}

EXT_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".kt": "Kotlin",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".cpp": "C++",
    ".c": "C",
    ".swift": "Swift",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".scala": "Scala",
    ".clj": "Clojure",
    ".hs": "Haskell",
}
