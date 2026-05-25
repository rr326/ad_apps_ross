# ad_apps_ross

Shared AppDaemon apps used by Ross's Home Assistant setups (Haven on
`hs1`, Seattle on `ss1` — consumed as a submodule from `rr326/haconfig`).

## ⚠️ Status (2026-05-25)

After the 2026-05 cleanup, some apps in this repo have divergent or
incomplete work that didn't make it into `main`:

- **sonos** — untrusted. An incomplete `pysonos → soco` migration
  lives in `old_master`; current `main` version is from `haven` and
  may also be flaky. Marker: branch `unmerged_sonos`.
- **dashboard_support** — `old_master` has a few "fixed away colors" /
  "valve vacation mode" / older "dashboard support for rinnai" commits
  that weren't merged. `main` (descended from `haven`) has more-recent
  versions of those features. Marker: branch `unmerged_dashboard`.
- **light_fade, gentlewakeup, backup_ha, wallmote** — apps not currently
  loaded on any host. See `old_master` if you ever need them.

Full divergence history is in the `old_master` branch.

Open shared-app TODOs (sonos fix, simplification audit) are tracked in
the consumer repo (`rr326/haconfig`) under `README_shared.md`.

## Apps

| Module | Status |
|---|---|
| `dashboard_support` | active on hs1; see ⚠️ Status |
| `sonos` | enabled on hs1 but untrusted; see ⚠️ Status |
| `light_fade` | not loaded anywhere |
| `gentlewakeup` | not loaded anywhere |
| `backup_ha` | disabled on hs1; ss1 has its own variant in `apps_3408/` |

Each app's yaml config (in the consuming host's `apps/config/` dir)
controls whether it actually runs.
