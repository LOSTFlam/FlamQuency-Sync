#!/usr/bin/env python3
"""Генератор completion-скриптов для flamquency (bash/zsh/fish).

Источник правды — тот же argparse, что использует CLI, поэтому новые
команды и флаги автоматически попадают в completion без ручной правки
трёх файлов.

    python scripts/gen-completions.py            # пишет в completions/
    python scripts/gen-completions.py --stdout   # печатает все три

Скрипты намеренно простые и самодостаточные: без внешних зависимостей в
оболочке, с динамическими подсказками (профили, бэкенды, снапшоты) через
вызов самого flamquency.
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from flamquency.cli import build_parser

BASH_TEMPLATE = '''# Bash completion for flamquency — сгенерировано scripts/gen-completions.py
# Перечитывает список команд напрямую у CLI, поэтому не устаревает.
_flamquency() {{
    local cur prev words cword
    _init_completion 2>/dev/null || {{
        COMPREPLY=()
        cur="${{COMP_WORDS[COMP_CWORD]}}"
        prev="${{COMP_WORDS[COMP_CWORD-1]}}"
        words=("${{COMP_WORDS[@]}}")
        cword=$COMP_CWORD
    }}

    if [ "$cword" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "{commands}" -- "$cur") )
        return 0
    fi

    case "${{words[1]}}" in
{dynamic_cases}        *) COMPREPLY=( $(compgen -f -- "$cur") ) ;;
    esac
    return 0
}}
complete -F _flamquency flamquency
'''

BASH_DYNAMIC = {
    "profile": 'flamquency profile list 2>/dev/null | awk \'/^ /{{print $2}}\'',
    "backend": 'flamquency backend 2>/dev/null | awk \'/^ +(→)? *[a-z]/{{print $NF}}\' | head -8',
    "snapshots": 'flamquency snapshots 2>/dev/null | awk \'/^[0-9]+\\./{{print $1}}\'',
}

ZSH_TEMPLATE = '''#compdef flamquency
# Zsh completion for flamquency — сгенерировано scripts/gen-completions.py
_flamquency() {{
    local -a commands
    commands=(
{command_lines}    )
    _arguments -C \\
        '1: :->command' \\
        '*:: :->args'
    case $state in
        command)
            _describe 'command' commands
            ;;
        args)
            case $words[1] in
{dynamic_cases}            esac
            ;;
    esac
}}
_flamquency "$@"
'''

FISH_TEMPLATE = '''# Fish completion for flamquency — сгенерировано scripts/gen-completions.py
complete -c flamquency -f

{command_lines}
complete -c flamquency -n '__fish_use_subcommand' -a help -d 'Detailed help for a command'

# Динамические подсказки: значения берутся у самого flamquency
complete -c flamquency -n '__fish_seen_subcommand_from profile; and __fish_seen_subcommand_from use show delete add-path remove-path describe' \\
    -a '(flamquency profile list 2>/dev/null | string match -r "^ +\\S+" | string trim)'
complete -c flamquency -n '__fish_seen_subcommand_from sync rollback prune restore-tree' -a '--profile=(flamquency profile list 2>/dev/null | string match -r "^ +\\S+" | string trim)'
complete -c flamquency -n '__fish_seen_subcommand_from backend; and __fish_seen_subcommand_from use check' \\
    -a '(flamquency backend 2>/dev/null | string match -r "^ +[a-z0-9-]+ " | string trim)'
'''


def collect_commands():
    """Команды из argparse: [(имя, help)] в порядке объявления."""
    parser = build_parser()
    subparsers = None
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            subparsers = action
            break
    if subparsers is None:
        return []
    rows = []
    for name, sub in subparsers.choices.items():
        # help команды лежит в метаданных самого subparsers-действия
        choice_action = getattr(subparsers, "_choices_actions", None) or []
        help_text = ""
        for act in choice_action:
            if act.dest == name:
                help_text = act.help or ""
                break
        rows.append((name, help_text.replace("'", "")))
    return rows


def gen_bash(commands):
    names = " ".join(name for name, _ in commands)
    cases = []
    for cmd, dynamic in BASH_DYNAMIC.items():
        cases.append(
            f'        {cmd})\n'
            f'            COMPREPLY=( $(compgen -W "$({dynamic})" -- "$cur") )\n'
            f'            return 0\n'
            f'            ;;\n')
    return BASH_TEMPLATE.format(commands=names, dynamic_cases="".join(cases))


def gen_zsh(commands):
    lines = []
    for name, help_text in commands:
        escaped = help_text.replace("'", "'\\''").replace(":", "\\:")
        lines.append(f"        '{name}:{escaped}'\n")
    cases = []
    for cmd, dynamic in BASH_DYNAMIC.items():
        cases.append(
            f'                {cmd})\n'
            '                    _values \'value\' $(' + dynamic + ')\n'
            '                    ;;\n')
    return ZSH_TEMPLATE.format(command_lines="".join(lines),
                               dynamic_cases="".join(cases))


def gen_fish(commands):
    lines = []
    for name, help_text in commands:
        escaped = help_text.replace("'", "\\'")
        lines.append(f"complete -c flamquency -n '__fish_use_subcommand' -a {name} -d '{escaped}'\n")
    return FISH_TEMPLATE.format(command_lines="".join(lines))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdout", action="store_true",
                        help="Print all three scripts instead of writing files")
    parser.add_argument("--out-dir", default=str(REPO / "completions"),
                        help="Where to write the scripts")
    args = parser.parse_args()

    commands = collect_commands()
    if not commands:
        print("Не удалось собрать команды из argparse", file=sys.stderr)
        return 1

    scripts = {
        "flamquency.bash": gen_bash(commands),
        "flamquency.zsh": gen_zsh(commands),
        "flamquency.fish": gen_fish(commands),
    }

    if args.stdout:
        for name, text in scripts.items():
            print(f"===== {name} =====")
            print(text)
        return 0

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in scripts.items():
        (out_dir / name).write_text(text)
        print(f"✓ {out_dir / name} ({len(commands)} команд)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
