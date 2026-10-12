# Bash completion for flamquency
_flamquency() {
    local cur prev opts
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    if [ "$COMP_CWORD" -eq 1 ]; then
        opts="sync status snapshots rollback rollback-file diff watch config encryption ignore profile"
        COMPREPLY=( $(compgen -W "${opts}" -- "${cur}") )
        return 0
    fi

    case "${prev}" in
        sync)
            COMPREPLY=( $(compgen -f -- "${cur}") )
            return 0
            ;;
        --profile|-P)
            COMPREPLY=( $(compgen -W "$(flamquency profile list 2>/dev/null | awk '/^ /{print $2}')" -- "${cur}") )
            return 0
            ;;
        rollback)
            COMPREPLY=( $(compgen -W "--snapshot --list" -- "${cur}") )
            return 0
            ;;
        rollback-file)
            COMPREPLY=( $(compgen -f -- "${cur}") )
            return 0
            ;;
        diff)
            COMPREPLY=( $(compgen -f -- "${cur}") )
            return 0
            ;;
        watch)
            COMPREPLY=( $(compgen -d -- "${cur}") )
            return 0
            ;;
        config)
            COMPREPLY=( $(compgen -W "--edit" -- "${cur}") )
            return 0
            ;;
        profile)
            COMPREPLY=( $(compgen -W "list create delete use show add-path remove-path describe --path --description --exclude" -- "${cur}") )
            return 0
            ;;
        encryption|ignore)
            COMPREPLY=( $(compgen -f -- "${cur}") )
            return 0
            ;;
    esac

    COMPREPLY=( $(compgen -f -- "${cur}") )
    return 0
}
complete -F _flamquency flamquency
