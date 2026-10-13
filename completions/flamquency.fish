# Fish completion for flamquency — сгенерировано scripts/gen-completions.py
complete -c flamquency -f

complete -c flamquency -n '__fish_use_subcommand' -a sync -d 'Synchronize files'
complete -c flamquency -n '__fish_use_subcommand' -a rollback -d 'Rollback to snapshot'
complete -c flamquency -n '__fish_use_subcommand' -a rollback-file -d 'Rollback specific file'
complete -c flamquency -n '__fish_use_subcommand' -a restore-content -d 'Restore the content of a specific version to any path'
complete -c flamquency -n '__fish_use_subcommand' -a view-content -d 'Print the content of a specific version (no restore)'
complete -c flamquency -n '__fish_use_subcommand' -a restore-tree -d 'Restore a whole directory, a profile, or the entire store'
complete -c flamquency -n '__fish_use_subcommand' -a schedule -d 'Set up a recurring sync schedule (cron / Task Scheduler)'
complete -c flamquency -n '__fish_use_subcommand' -a backend -d 'Manage storage backends: list / use / check'
complete -c flamquency -n '__fish_use_subcommand' -a evolve -d '«Эволюция»: самообучение на привычках и предложения'
complete -c flamquency -n '__fish_use_subcommand' -a spark -d '«Огниво» — run your own quick actions'
complete -c flamquency -n '__fish_use_subcommand' -a echo -d '«Эхо памяти» — suggest paths to sync from shell history'
complete -c flamquency -n '__fish_use_subcommand' -a kaleido -d '«Калейдоскоп» — colour variations of the «Угольки» theme'
complete -c flamquency -n '__fish_use_subcommand' -a help -d 'Rich, detailed help for one command'
complete -c flamquency -n '__fish_use_subcommand' -a status -d 'Show sync status'
complete -c flamquency -n '__fish_use_subcommand' -a diff -d 'Diff two versions of a file'
complete -c flamquency -n '__fish_use_subcommand' -a snapshots -d 'List snapshots'
complete -c flamquency -n '__fish_use_subcommand' -a init -d 'Quick setup: config, ignore file, retention'
complete -c flamquency -n '__fish_use_subcommand' -a prune -d 'Prune old snapshots (restic-style retention)'
complete -c flamquency -n '__fish_use_subcommand' -a check -d 'Verify blob store integrity'
complete -c flamquency -n '__fish_use_subcommand' -a stats -d 'Storage statistics and charts'
complete -c flamquency -n '__fish_use_subcommand' -a update -d 'Check and install updates'
complete -c flamquency -n '__fish_use_subcommand' -a watch -d 'Watch mode — auto-sync'
complete -c flamquency -n '__fish_use_subcommand' -a config -d 'Show/edit configuration'
complete -c flamquency -n '__fish_use_subcommand' -a encryption -d 'Manage blob encryption'
complete -c flamquency -n '__fish_use_subcommand' -a ignore -d 'Manage ~/.flamquencyignore (gitignore-style rules)'
complete -c flamquency -n '__fish_use_subcommand' -a profile -d 'Manage sync profiles (named sets of paths)'

complete -c flamquency -n '__fish_use_subcommand' -a help -d 'Detailed help for a command'

# Динамические подсказки: значения берутся у самого flamquency
complete -c flamquency -n '__fish_seen_subcommand_from profile; and __fish_seen_subcommand_from use show delete add-path remove-path describe' \
    -a '(flamquency profile list 2>/dev/null | string match -r "^ +\S+" | string trim)'
complete -c flamquency -n '__fish_seen_subcommand_from sync rollback prune restore-tree' -a '--profile=(flamquency profile list 2>/dev/null | string match -r "^ +\S+" | string trim)'
complete -c flamquency -n '__fish_seen_subcommand_from backend; and __fish_seen_subcommand_from use check' \
    -a '(flamquency backend 2>/dev/null | string match -r "^ +[a-z0-9-]+ " | string trim)'
