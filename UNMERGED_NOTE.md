# unmerged_dashboard

Marker branch tracking that **dashboard_support has divergent unmerged
work** that did not land in `main` during the 2026-05 cleanup.

What's in `old_master` for dashboard_support that's NOT in `main`:
- `6c2e040` / `ef106af` / `2409409` "fixed away colors" series
- `7e20ad6` not doing colors for valve vacation mode
- `0872fbb` dashboard support for rinnai (older parallel impl)
- `c865815` tweaks
- (debug cleanup commits brought in to main; see git history)

Reason not cherry-picked: `main` (descended from `haven`) has more-recent
implementations of away-color logic and rinnai support, and the older
master versions may regress or duplicate. Worth a careful side-by-side
diff if you want to revisit.

Brought into main as part of the same cleanup:
- `bc56628` Fixed warning where new entity is created on first read.
  _silent=True (the explicit warning fix the user wanted)

This branch is a signpost only. Do not develop on it.
