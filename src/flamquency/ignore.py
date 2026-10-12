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
IGNORE_TEMPLATE_VERSION = 2

# ── Глобальные правила по размеру и типу (v2.0) ───────────────
# Отдельный синтаксис, не пересекающийся с glob-строками файла:
#
#   size>1GB        — файлы больше 1 ГиБ
#   size>=500MB     — от 500 МиБ включительно
#   size<10KB       — мельче 10 КиБ
#   type=mp4,avi    — по расширению (без точки, регистр не важен)
#
# Правила применяются ПОСЛЕ файловых: последнее совпадение решает, поэтому
# файловое `!важное.mkv` всё ещё перебьёт `type=mkv`.

_SIZE_UNITS = {
    "B": 1, "K": 1024, "KB": 1024, "M": 1024 ** 2, "MB": 1024 ** 2,
    "G": 1024 ** 3, "GB": 1024 ** 3, "T": 1024 ** 4, "TB": 1024 ** 4,
    "KIB": 1024, "MIB": 1024 ** 2, "GIB": 1024 ** 3, "TIB": 1024 ** 4,
}

_SIZE_RE = re.compile(
    r"^size\s*(>=|<=|>|<|=)\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]*)$")
_TYPE_RE = re.compile(r"^type\s*=\s*([A-Za-z0-9_,\s]+)$")


def parse_size(text):
    """«1GB» / «500 MB» / «1024» → байты (int). None если не разобрать."""
    text = str(text).strip().upper().replace(" ", "")
    m = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([A-Z]*)", text)
    if not m:
        return None
    value, unit = m.groups()
    factor = _SIZE_UNITS.get(unit, 1) if unit else 1
    return int(float(value) * factor)


class SizeRule:
    """Правило по размеру файла: ``size>1GB``."""

    kind = "size"

    def __init__(self, operator, threshold_bytes):
        self.operator = operator
        self.threshold = int(threshold_bytes)

    @classmethod
    def parse(cls, text):
        m = _SIZE_RE.match(str(text).strip())
        if not m:
            return None
        operator, value, unit = m.groups()
        # «1 GB» с пробелом внутри — уберём пробелы перед единицей
        unit = unit.strip()
        size = parse_size(f"{value}{unit}")
        if size is None:
            return None
        return cls(operator, size)

    def matches(self, rel_path, is_dir=False, size=None):
        if is_dir or size is None:
            return False
        if self.operator == ">":
            return size > self.threshold
        if self.operator == ">=":
            return size >= self.threshold
        if self.operator == "<":
            return size < self.threshold
        if self.operator == "<=":
            return size <= self.threshold
        return size == self.threshold

    def describe(self):
        return f"размер {self.operator} {self.threshold} B"

    @property
    def raw(self):
        """Строковая форма — для единообразного вывода в CLI."""
        return f"size{self.operator}{self.threshold}"

    def __repr__(self):
        return f"SizeRule({self.raw})"


class TypeRule:
    """Правило по расширению: ``type=mp4,avi,mkv``."""

    kind = "type"

    def __init__(self, extensions):
        self.extensions = {e.lower().lstrip(".") for e in extensions if e}

    @classmethod
    def parse(cls, text):
        m = _TYPE_RE.match(str(text).strip())
        if not m:
            return None
        raw = m.group(1).replace(",", " ").split()
        if not raw:
            return None
        return cls(raw)

    def matches(self, rel_path, is_dir=False, size=None):
        if is_dir:
            return False
        suffix = Path(rel_path).suffix.lower().lstrip(".")
        return bool(suffix) and suffix in self.extensions

    def describe(self):
        return "тип: " + ", ".join(sorted(self.extensions))

    @property
    def raw(self):
        """Строковая форма — для единообразного вывода в CLI."""
        return "type=" + ",".join(sorted(self.extensions))

    def __repr__(self):
        return f"TypeRule({self.raw})"


def parse_global_rule(text):
    """Строка → SizeRule / TypeRule, либо None если это не их синтаксис."""
    return SizeRule.parse(text) or TypeRule.parse(text)


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

    def __init__(self, rules=None, path=None, global_rules=None):
        self.rules = list(rules or [])
        self.path = Path(path) if path else None
        # Глобальные правила (size/type) из конфига — не из файла.
        self.global_rules = list(global_rules or [])

    # ── construction ───────────────────────────────────────────

    @classmethod
    def from_lines(cls, lines, path=None, global_rules=None):
        rules = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Глобальный синтаксис прямо в файле — тоже поддерживаем
            parsed = parse_global_rule(stripped)
            if parsed is not None:
                if global_rules is None:
                    rules.append(parsed)
                else:
                    global_rules.append(parsed)
                continue
            rules.append(IgnoreRule(stripped))
        return cls(rules, path=path, global_rules=global_rules or [])

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
    def from_config(cls, config, path=None):
        """Файловые правила + глобальные size/type из конфига."""
        rules = cls.from_file(path) if path else cls([])
        rules.global_rules = _global_rules_from_config(config)
        return rules

    @classmethod
    def empty(cls):
        return cls([])

    # ── queries ────────────────────────────────────────────────

    def __len__(self):
        return len(self.rules) + len(self.global_rules)

    def __iter__(self):
        return iter(list(self.rules) + list(self.global_rules))

    def __bool__(self):
        return bool(self.rules) or bool(self.global_rules)

    def match(self, rel_path, is_dir=False, size=None):
        """Last matching rule wins; no match means the path is kept.

        `size` (bytes) активирует правила ``size>``/``size<``. Без него
        глобальные size-правила просто не срабатывают — это нормально
        для предварительной проверки по одному пути.

        Оба списка правил (файловые и глобальные) просматриваются одним
        проходом: правило из файла и правило из конфига равноправны, и
        «последнее совпадение решает» работает между ними тоже.
        """
        ignored = False
        for rule in self.rules:
            ignored = self._apply(rule, rel_path, is_dir, size, ignored)
        for rule in self.global_rules:
            ignored = self._apply(rule, rel_path, is_dir, size, ignored)
        return ignored

    @staticmethod
    def _apply(rule, rel_path, is_dir, size, current):
        """Применить одно правило к текущему решению."""
        try:
            hit = rule.matches(rel_path, is_dir=is_dir, size=size)
        except TypeError:
            # У файлового IgnoreRule нет параметра size
            hit = rule.matches(rel_path, is_dir=is_dir)
        if not hit:
            return current
        return not getattr(rule, "negate", False)

    def explain(self, rel_path, is_dir=False, size=None):
        """Like match() but also returns the deciding rule (or None)."""
        ignored = False
        decider = None
        for rule in list(self.rules) + list(self.global_rules):
            try:
                hit = rule.matches(rel_path, is_dir=is_dir, size=size)
            except TypeError:
                hit = rule.matches(rel_path, is_dir=is_dir)
            if not hit:
                continue
            ignored = not getattr(rule, "negate", False)
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


def _global_rules_from_config(config):
    """Глобальные size/type-правила из конфига (``ignore_size_gt`` и т.п.)."""
    rules = []
    if not config:
        return rules
    # Одиночные правила: ignore_size_gt / ignore_size_lt
    for key, operator in (("ignore_size_gt", ">"), ("ignore_size_gte", ">="),
                          ("ignore_size_lt", "<"), ("ignore_size_lte", "<=")):
        value = config.get(key)
        if value in (None, ""):
            continue
        size = parse_size(value)
        if size is not None:
            rules.append(SizeRule(operator, size))
    # Список типов: ignore_types
    types = config.get("ignore_types")
    if types:
        if isinstance(types, str):
            types = types.replace(",", " ").split()
        rule = TypeRule.parse("type=" + ",".join(str(t) for t in types))
        if rule:
            rules.append(rule)
    return rules


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
