# Bash completion for flamquency — сгенерировано scripts/gen-completions.py
# Перечитывает список команд напрямую у CLI, поэтому не устаревает.
_flamquency() {
    local cur prev words cword
    _init_completion 2>/dev/null || {
        COMPREPLY=()
        cur="${COMP_WORDS[COMP_CWORD]}"
        prev="${COMP_WORDS[COMP_CWORD-1]}"
        words=("${COMP_WORDS[@]}")
        cword=$COMP_CWORD
    }

    if [ "$cword" -eq 1 ]; then
        COMPREPLY=( $(compgen -W "sync rollback rollback-file restore-content view-content restore-tree schedule backend evolve spark echo kaleido help status diff snapshots init prune check stats update watch config encryption ignore profile" -- "$cur") )
        return 0
    fi

    case "${words[1]}" in
        profile)
            COMPREPLY=( $(compgen -W "$(flamquency profile list 2>/dev/null | awk '/^ /{{print $2}}')" -- "$cur") )
            return 0
            ;;
        backend)
            COMPREPLY=( $(compgen -W "$(flamquency backend 2>/dev/null | awk '/^ +(→)? *[a-z]/{{print $NF}}' | head -8)" -- "$cur") )
            return 0
            ;;
        snapshots)
            COMPREPLY=( $(compgen -W "$(flamquency snapshots 2>/dev/null | awk '/^[0-9]+\./{{print $1}}')" -- "$cur") )
            return 0
            ;;
        *) COMPREPLY=( $(compgen -f -- "$cur") ) ;;
    esac
    return 0
}
complete -F _flamquency flamquency
