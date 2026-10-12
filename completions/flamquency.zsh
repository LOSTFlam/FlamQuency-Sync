#compdef flamquency
# Zsh completion for flamquency

_flamquency() {
    local -a commands
    commands=(
        'sync:Synchronize files'
        'status:Show sync status'
        'snapshots:List snapshots'
        'rollback:Rollback to snapshot'
        'rollback-file:Rollback specific file'
        'diff:Diff two versions of a file'
        'watch:Watch mode — auto-sync'
        'config:Show or edit configuration'
        'encryption:Manage blob encryption'
        'ignore:Manage .flamquencyignore rules'
        'profile:Manage sync profiles'
    )

    _arguments -C \
        '1: :->command' \
        '*::arg:->args'

    case $state in
        command)
            _describe 'command' commands
            ;;
        args)
            case $words[1] in
                sync|diff|rollback-file)
                    _files
                    ;;
                watch)
                    _directories
                    ;;
                profile)
                    _values 'action' list create delete use show add-path remove-path describe
                    ;;
            esac
            ;;
    esac
}

_flamquency "$@"
