""".flamquencyignore — gitignore-style exclusion rules for FlamQuency-Sync.

Lives in the user's home directory as `~/.flamquencyignore`. Syntax follows
the familiar .gitignore rules so users don't have to learn anything new:

    # comment
    *.log              — ignore every .log at any depth
    !keep.log          — negation: re-include (last matching rule wins)
    build/             — directories only (trailing slash)
    /rooted.txt        — anchored to the ignore file's directory
    **/node_modules    — ** crosses directory boundaries
    temp?.tmp          — ? matches exactly one character
    [abc]*.txt         — character classes work too

Matching is per-path: rules are evaluated in order and the LAST matching
rule decides. No match means the file is kept.
"""
import re
from pathlib import Path

IGNORE_FILENAME = ".flamquencyignore"

# Bumped when the default template's *active* rules change so stale user
# copies can be refreshed with --force.
IGNORE_TEMPLATE_VERSION = 1


class IgnoreRule:
    """One parsed line from an ignore file."""

    __slots__ = ("raw", "negate", "dir_only", "anchored", "pattern", "_regex")

    def __init__(self, raw):
        self.raw = raw.strip()
        pattern = self.raw

        # Negation — re-include an otherwise-ignored path
        self.negate = pattern.startswith("!")
        if self.negate:
            pattern = pattern[1:]

        # Directory-only — trailing slash
        self.dir_only = pattern.endswith("/")
        if self.dir_only:
            pattern = pattern.rstrip("/")

        # Anchored — a LEADING slash binds the pattern to the ignore file's
        # directory; a slash anywhere else (but trailing) does the same.
        # Same rule gitignore uses.
        had_leading_slash = pattern.startswith("/")
        core = pattern.lstrip("/")
        self.anchored = had_leading_slash or "/" in core

        self.pattern = core
        self._regex = self._compile(core, self.anchored)

    # ── compilation ────────────────────────────────────────────

    @staticmethod
    def _compile(pattern, anchored):
        """Translate a glob into a regex over a POSIX-style relative path.

        `**` crosses '/', `*` and `?` do not. Character classes are passed
        through; everything else is literal.
        """
        i, n = 0, len(pattern)
        out = []
        while i < n:
            c = pattern[i]
            if c == "*":
                if pattern.startswith("**", i):
                    # consume the whole run of stars
                    j = i
                    while j < n and pattern[j] == "*":
                        j += 1
                    stars = j - i
                    if stars >= 2:
                        if j < n and pattern[j] == "/":
                            # "**/" → zero or more leading directories
                            out.append("(?:[^/]+/)*")
                            i = j + 1
                        else:
                            # "**" → anything, including '/'
                            out.append(".*")
                            i = j
                    else:
                        out.append("[^/]*")
                        i = j
                else:
                    out.append("[^/]*")
                    i += 1
            elif c == "?":
                out.append("[^/]")
                i += 1
            elif c == "[":
                # character class — copy until the closing bracket
                j = i + 1
                if j < n and pattern[j] in ("!", "^"):
                    j += 1
                if j < n and pattern[j] == "]":
                    j += 1
                while j < n and pattern[j] != "]":
                    j += 1
                if j >= n:
                    out.append(re.escape("["))
                    i += 1
                else:
                    cls = pattern[i + 1:j]
                    if cls.startswith("!"):
                        cls = "^" + cls[1:]
                    out.append("[" + cls + "]")
                    i = j + 1
            else:
                out.append(re.escape(c))
                i += 1
        body = "".join(out)
        if anchored:
            # anchored: match from the start of the relative path
            return re.compile("^" + body + "$")
        # unanchored: match the basename at any depth
        return re.compile("^(?:.*/)?" + body + "$")

    # ── matching ───────────────────────────────────────────────

    def matches(self, rel_path, is_dir=False):
        """Does this rule apply to `rel_path` (a POSIX relative path)?"""
        if self.dir_only and not is_dir:
            # "build/" ignores the directory and everything under it.
            # A file arriving with is_dir=False is covered when one of its
            # ANCESTOR directories matches — a file literally named "build"
            # at the same spot is kept.
            parts = rel_path.split("/")
            for i in range(1, len(parts)):
                if self._regex.match("/".join(parts[:i])):
                    return True
            return False
        return bool(self._regex.match(rel_path))

    def __repr__(self):
        return f"IgnoreRule({self.raw!r})"


class IgnoreRules:
    """The full rule set loaded from an ignore file."""

    def __init__(self, rules=None, path=None):
        self.rules = list(rules or [])
        self.path = Path(path) if path else None

    # ── construction ───────────────────────────────────────────

    @classmethod
    def from_lines(cls, lines, path=None):
        rules = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            rules.append(IgnoreRule(stripped))
        return cls(rules, path=path)

    @classmethod
    def from_file(cls, path):
        """Load rules from `path`; a missing file simply yields no rules."""
        path = Path(path)
        if not path.exists():
            return cls([], path=path)
        try:
            text = path.read_text()
        except OSError:
            return cls([], path=path)
        return cls.from_lines(text.splitlines(), path=path)

    @classmethod
    def empty(cls):
        return cls([])

    # ── queries ────────────────────────────────────────────────

    def __len__(self):
        return len(self.rules)

    def __iter__(self):
        return iter(self.rules)

    def __bool__(self):
        return bool(self.rules)

    def match(self, rel_path, is_dir=False):
        """Last matching rule wins; no match means the path is kept."""
        ignored = False
        for rule in self.rules:
            if rule.matches(rel_path, is_dir=is_dir):
                ignored = not rule.negate
        return ignored

    def explain(self, rel_path, is_dir=False):
        """Like match() but also returns the deciding rule (or None)."""
        ignored = False
        decider = None
        for rule in self.rules:
            if rule.matches(rel_path, is_dir=is_dir):
                ignored = not rule.negate
                decider = rule
        return ignored, decider

    def match_path(self, path, base=None, is_dir=None):
        """Convenience: match an absolute/relative Path against the rules.

        `base` is the directory the ignore file lives in (usually home);
        the path is made relative to it before matching.
        """
        path = Path(path)
        if is_dir is None:
            is_dir = path.is_dir()
        if base is not None:
            try:
                rel = path.relative_to(Path(base))
            except ValueError:
                # outside the base — fall back to the full path
                rel = path
        else:
            rel = path
        return self.match(rel.as_posix(), is_dir=is_dir)


def default_template():
    """The starter .flamquencyignore written by `flamquency ignore --init`."""
    return f"""\
# FlamQuency-Sync ignore rules — syntax works like .gitignore
# Docs: https://github.com/LOSTFlam/FlamQuency-Sync
#
#   *.log          ignore every .log at any depth
#   !keep.log      negation — re-include (last matching rule wins)
#   build/         directories only (trailing slash)
#   /rooted.txt    anchored to the home directory
#   **/node_modules  ** crosses directory boundaries
#
# Lines starting with # are comments; blank lines are ignored.

# --- noise you almost never want versioned -------------------
*.log
*.tmp
*.swp
*~
**/__pycache__/**
**/*.pyc
**/.DS_Store
**/Thumbs.db
**/.cache/**

# --- big build artifacts -------------------------------------
**/node_modules/**
**/target/**
**/build/**
**/dist/**
**/.venv/**
**/venv/**

# --- secrets — keep these OUT of sync ------------------------
**/*.pem
**/*.key
**/id_rsa*
**/.env
**/.env.*
!**/.env.example
"""


def default_ignore_path():
    """Where the user's ignore file lives: ~/.flamquencyignore."""
    return Path.home() / IGNORE_FILENAME


def write_default_ignore_file(path=None, force=False):
    """Create the default ignore file if it doesn't exist yet.

    Returns the path written, or None when the file already existed and
    `force` is False (we never clobber the user's rules silently).
    """
    path = Path(path) if path else default_ignore_path()
    if path.exists() and not force:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_template())
    return path


def load_ignore_rules(path=None, use=True):
    """Load the user's rules (or an empty set when disabled/missing)."""
    if not use:
        return IgnoreRules.empty()
    if path is None:
        path = default_ignore_path()
    return IgnoreRules.from_file(path)
