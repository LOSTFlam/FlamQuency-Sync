# Fish completion for flamquency

complete -c flamquency -f

complete -c flamquency -n '__fish_use_subcommand' -a sync -d 'Synchronize files'
complete -c flamquency -n '__fish_use_subcommand' -a status -d 'Show sync status'
complete -c flamquency -n '__fish_use_subcommand' -a snapshots -d 'List snapshots'
complete -c flamquency -n '__fish_use_subcommand' -a rollback -d 'Rollback to snapshot'
complete -c flamquency -n '__fish_use_subcommand' -a rollback-file -d 'Rollback specific file'
complete -c flamquency -n '__fish_use_subcommand' -a diff -d 'Diff two versions of a file'
complete -c flamquency -n '__fish_use_subcommand' -a watch -d 'Watch mode — auto-sync'
complete -c flamquency -n '__fish_use_subcommand' -a config -d 'Show or edit configuration'

complete -c flamquency -n '__fish_use_subcommand' -a profile -d 'Manage sync profiles'
complete -c flamquency -n '__fish_seen_subcommand_from profile' -a list -d 'List profiles'
complete -c flamquency -n '__fish_seen_subcommand_from profile' -a create -d 'Create a profile'
complete -c flamquency -n '__fish_seen_subcommand_from profile' -a delete -d 'Delete a profile'
complete -c flamquency -n '__fish_seen_subcommand_from profile' -a use -d 'Set the active profile'
complete -c flamquency -n '__fish_seen_subcommand_from profile' -a show -d 'Show one profile'
complete -c flamquency -n '__fish_seen_subcommand_from profile' -a add-path -d 'Add a path'
complete -c flamquency -n '__fish_seen_subcommand_from profile' -a remove-path -d 'Remove a path'
complete -c flamquency -n '__fish_seen_subcommand_from profile' -a describe -d 'Set description'
complete -c flamquency -n '__fish_seen_subcommand_from profile' -l path -d 'Path (repeatable)'
complete -c flamquency -n '__fish_seen_subcommand_from profile' -l description -d 'Profile description'
complete -c flamquency -n '__fish_seen_subcommand_from profile' -l exclude -d 'Extra exclude pattern'

complete -c flamquency -n '__fish_seen_subcommand_from sync' -l profile -d 'Sync this profile'

complete -c flamquency -n '__fish_seen_subcommand_from rollback' -l snapshot -d 'Snapshot index'
complete -c flamquency -n '__fish_seen_subcommand_from rollback' -l list -d 'List snapshots'
complete -c flamquency -n '__fish_seen_subcommand_from rollback-file' -l version -d 'Version index'
complete -c flamquency -n '__fish_seen_subcommand_from rollback-file' -l list -d 'List versions'
complete -c flamquency -n '__fish_seen_subcommand_from diff' -l v1 -d 'First version'
complete -c flamquency -n '__fish_seen_subcommand_from diff' -l v2 -d 'Second version'
complete -c flamquency -n '__fish_seen_subcommand_from config' -l edit -d 'Edit config'
complete -c flamquency -n '__fish_seen_subcommand_from sync' -l source -d 'Source directory'
