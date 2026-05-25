# unmerged_sonos

Marker branch tracking that **sonos has divergent unmerged work** that
did not land in `main` during the 2026-05 cleanup.

What's in `old_master` for sonos:
- `542a4fe` BEGINNING upgrading from pysonos to soco. NOT WORKING
- `ac4523b` fixed bug in sonos probably upgraded sonos version
- `a47dbf5` Updated how I handle sonos. Seems to be working.
- `47da5dd` tweaked sonos
- (plus debugging-only commits)

These were NOT cherry-picked because the migration is incomplete and
the current `main` version (descended from `haven`) at least runs.
If you ever want to revisit the soco migration, start from
`old_master` and audit those commits.

This branch is a signpost only. Do not develop on it.
