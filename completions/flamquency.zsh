#compdef flamquency
# Zsh completion for flamquency — сгенерировано scripts/gen-completions.py
_flamquency() {
    local -a commands
    commands=(
        'sync:Synchronize files'
        'rollback:Rollback to snapshot'
        'rollback-file:Rollback specific file'
        'restore-content:Restore the content of a specific version to any path'
        'view-content:Print the content of a specific version (no restore)'
        'restore-tree:Restore a whole directory, a profile, or the entire store'
        'schedule:Set up a recurring sync schedule (cron / Task Scheduler)'
        'backend:Manage storage backends\: list / use / check'
        'evolve:«Эволюция»\: самообучение на привычках и предложения'
        'status:Show sync status'
        'diff:Diff two versions of a file'
        'snapshots:List snapshots'
        'init:Quick setup\: config, ignore file, retention'
        'prune:Prune old snapshots (restic-style retention)'
        'check:Verify blob store integrity'
        'stats:Storage statistics and charts'
        'update:Check and install updates'
        'watch:Watch mode — auto-sync'
        'config:Show/edit configuration'
        'encryption:Manage blob encryption'
        'ignore:Manage ~/.flamquencyignore (gitignore-style rules)'
        'profile:Manage sync profiles (named sets of paths)'
    )
    _arguments -C \
        '1: :->command' \
        '*:: :->args'
    case $state in
        command)
            _describe 'command' commands
            ;;
        args)
            case $words[1] in
                profile)
                    _values 'value' $(flamquency profile list 2>/dev/null | awk '/^ /{{print $2}}')
                    ;;
                backend)
                    _values 'value' $(flamquency backend 2>/dev/null | awk '/^ +(→)? *[a-z]/{{print $NF}}' | head -8)
                    ;;
                snapshots)
                    _values 'value' $(flamquency snapshots 2>/dev/null | awk '/^[0-9]+\./{{print $1}}')
                    ;;
            esac
            ;;
    esac
}
_flamquency "$@"
