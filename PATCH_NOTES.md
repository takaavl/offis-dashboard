# v0.6.0 — Final polish pass

## Added
- Match cards now use a restrained result tint across the full header: teal for wins, coral/red for losses, while keeping the W/L badge for accessibility.
- Official VALORANT role symbols (Duelist / Initiator / Controller / Sentinel) are now stored locally and used on Core player cards and profiles.
- Player profiles were rebuilt as analyst profiles: hero identity block, compact performance summary, agent pool, roster context, visual map-performance cards, and five recent clickable maps.
- Overview rebuilt around a compact scoreboard, Core-vs-subs split, pistol split, map pool and recent series.

## Changed
- Dark theme lifted slightly so surfaces remain dark/mauve without crushing contrast.
- `/matches` gives substantially more visual weight to series score, map score and team composition. Map art remains in a dedicated block instead of sitting behind agents.
- Substitute controls and roster-status badges have explicit high-contrast states; labels remain visible so meaning is not color-only.
- `/maps` map art now anchors from the left and fades into the data surface.
- Most-used Core comp now shows `maps · WR` instead of `maps · wins`.
- `/compositions` map artwork is slightly more visible while preserving table readability.
- `/players` decorative subtitle removed.
- Player-profile `missed in dataset` copy removed.
- Overview subtitle reduced to one factual sentence: `Official match performance.`
- Match-detail insight descriptions shortened to factual labels.

## Fixed / verified
- Team-side player names still resolve to canonical player identity when someone played on another account. Verified on `/matches/35`: TempoKD is shown and `Takaa#VLT` is not.
- 89/89 application routes return HTTP 200 after the redesign.
- No match, map, player, event or historical data was changed in this UI pass.

## Known limitations
- Map/agent imagery still comes from the URLs stored in Tracker data; role icons are now local.
- Player hero artwork depends on the stored agent portrait URL and therefore shares that remote-asset limitation.

---

# v0.5.1 — Local asset hotfix

## Fixed
- Reverted the four Valorant role icons from remote `media.valorant-api.com` URLs to the packaged local SVG assets under `/static/roles/`.
- This removes the new external dependency introduced in v0.5 that could leave player cards/profile role UI visually broken on local installs.
- No database, match, player, map, composition, event, or historical data was changed.

## Data / QA
- 70 historical maps remain unchanged.
- Existing local role assets verified present: Duelist, Initiator, Controller, Sentinel.
- Static files remain served by FastAPI through `/static`.

## Known limitation
- Map and agent artwork still use the Tracker CDN URLs already present in the imported JSON. Those worked in v0.4 and are intentionally unchanged by this hotfix.

---

# W1Z Team Dashboard — Patch Notes

## v0.3.0 — Core-first UI pass

### Added
- New mauve/violet visual system across the whole dashboard: background, sidebar, cards, controls and highlights now use one coherent purple family instead of white-heavy panels.
- New match detail page at `/matches/{series_id}`.
- Full reconstructed match leaderboard from the stored raw Tracker JSON, including opponents when Tracker data is available.
- Player recent maps are limited to 5 and link directly to the relevant map section on the match page.
- Player cards now use the most-played agent portrait as a background.
- Players page now shows the Core first, with expandable sections for current subs and former/specific subs.
- Core / With subs / All toggle on the Maps page.
- Core / With subs toggle on the Compositions page.
- Premier event cards now display Regular Season and Playoffs records separately.
- Premier event detail pages split matches into Regular Season and Playoffs sections.
- Back buttons on player, match and event detail pages.
- BO3 series on Matches are expandable with map score, side start and team composition.

### Changed
- Player card K/D replaced by KDA = (kills + assists) / deaths.
- Player profile main stat block now emphasizes KDA, ACS, KAST, FK–FD and DDΔ/R rather than ADR.
- Player map performance now shows WR, ACS, KAST, FK–FD and DDΔ/R; ADR removed from the visual read.
- Agent visuals on player detail/composition/match views now use icon images; full portraits are reserved for player-card backgrounds.
- Composition display uses the coach-defined role order:
  - Double entry: ENTRY → ENTRY 2 → RECON/INIT → CONTROLLER → SENTI
  - Double duelist: ENTRY → RECON/INIT → 2ND DUEL → CONTROLLER → SENTI
  - Double init: ENTRY/DUEL → RECON → INIT 2 → CONTROLLER → SENTI
  - Double controller: ENTRY/DUEL → RECON/INIT → CONTROLLER 1 → CONTROLLER 2 → SENTI
  - Double senti: ENTRY/DUEL → RECON/INIT → CONTROLLER → SENTI 1 → SENTI 2
- Event match ordering is now most recent → oldest.
- Core remains the default competitive view wherever a Core/sub split exists.

### Fixed
- Added `agent_portrait_url` separately from `agent_image_url`, so agent icons and full artwork are no longer forced to use the same asset.
- Veto added to the Sentinel role map after the composition audit found 5 compositions where he was previously unclassified.
- Composition audit after fix: 34 unique compositions, 0 unclassified agents.

### Data health
- 70 maps imported / 0 skipped.
- 0 open data issues.
- Lost Puppies G1 remains a resolved expected 4v5 exception.
- YoruBese remains a resolved partial Tracker-data exception with the official 15–13 score preserved.

### Known limitations
- Agent/map images still use CDN URLs stored in the Tracker JSON. Local asset caching is not implemented yet.
- Opponent identities on match leaderboards are shown exactly as Riot IDs from Tracker; no persistent opponent-player identity layer exists yet.
- Composition role ordering is deterministic, but within duplicate-role slots (e.g. controller 1/controller 2) we currently use a fixed agent priority rather than tactical “primary/secondary” labels.

## v0.4.0 — Dark identity / team-neutral rebuild

### Added
- Team-neutral branding: no former team name in the visible interface.
- Burger-menu navigation replacing the persistent sidebar.
- Dark-mode-first visual system with violet as the main accent.
- Cinematic map art fades on match/map cards.
- Teamplay insights on match detail: team KAST, trades, assists, openings, clutches, plants/defuses and ATK/DEF round win rates.
- Core player role labels and role icons.
- Composition `All` dataset in addition to Core / With subs.
- ATK and DEF round win-rate insights on the Maps page.

### Changed
- Core player order is now Duke, Lindorm, Lugia, LJPH, CeCe.
- Core player cards are taller and more character-forward.
- Match dropdowns use `ATK` / `DEF`, wider spacing and more prominent compositions/scores.
- Match leaderboards display canonical team player names instead of borrowed Tracker account names.
- Player map-performance view uses KDA instead of ADR and keeps KAST / FK-FD / DDΔ-R alongside WR.
- Events rebuilt as a compact tournament timeline/list.

### Data / QA
- No database migration required.
- 70 existing maps remain untouched.
- Canonical-name display is resolved from `player_map_stats`, so borrowed-account maps are attributed to the actual player.

### Known limitations
- Agent/map art still comes from the remote URLs contained in Tracker exports; local asset caching is not implemented yet.
- Custom role icons are local UI assets; they are not official Riot role artwork.

## v0.5.0 — Product polish, UX & accessibility

### Added
- BO3 map tabs on match detail pages: one map visible at a time, hash-aware links still open the requested map.
- Expandable map cards with the most-used Core composition and five recent officials on that map.
- External event match links now open in a new tab to preserve event navigation context.
- Official in-game role icon assets (Duelist / Initiator / Controller / Sentinel) are used through Valorant API media URLs.
- Keyboard focus states and reduced-motion support.

### Changed
- Dark palette lifted to a softer charcoal/mauve range while keeping violet as the primary accent.
- Global visual language reduced excessive rounding/gradient/card decoration for a more analyst/product-oriented feel.
- `/matches`: series score enlarged substantially; map artwork moved into a dedicated map block instead of sitting behind the agent composition; compositions receive more visual weight.
- `/matches/{id}`: denser teamplay presentation, stronger score hierarchy, and analyst-style leaderboard treatment.
- Core player cards now support per-player portrait positioning so each most-played agent sits more naturally in the crop.
- `/compositions`: every map is collapsed on initial load; map artwork is integrated into a larger banner; text contrast and table readability increased.
- `/maps`: switched from static cards to expandable analyst cards while preserving Core / With subs / All filters.
- Event detail match links open in a separate tab.

### Accessibility
- Raised muted-text contrast and key border contrast.
- Win/loss remains encoded by text (`W` / `L`) in addition to color.
- Success/loss colors moved toward teal and coral to reduce red/green-only dependency.
- Added visible `:focus-visible` treatment for keyboard users.
- Added `prefers-reduced-motion` handling.

### Data / QA
- Historical dataset unchanged: 70 imported maps.
- Tested 89 application routes after the refactor: 89/89 returned HTTP 200.
- No new data-health issue introduced.

### Known limitations
- Role icons currently use Valorant API media URLs rather than local packaged files. They are the game role icons, but still require internet access until assets are localized.
- Map and agent artwork still use remote URLs from the imported Tracker data.

## v0.7.0 — Constrained media pass

### Changed
- Rebuilt player profile hero around a fixed two-column layout. Agent art is now contained in a dedicated media frame using `object-fit: contain`; it can no longer stretch or dictate hero geometry.
- Rebuilt match-map header into two fixed modules: map artwork/score on the left and roster/composition context on the right.
- Removed free-floating/cinematic map backgrounds from match detail panels.
- Confined `/maps` artwork to the summary/header region so expanded analytics remain on a clean surface.

### Fixed
- Agent portraits no longer overflow, crop unpredictably, or stretch across the full player hero.
- Match map artwork no longer sits behind unrelated content or creates oversized empty visual areas.
- Expanded map cards no longer carry the map artwork through the full detail drawer.

### Data
- No database, match, roster, composition, event, or player-stat data changed in this release.

## v0.7.1 — Visual polish hotfix

### Fixed
- Re-cropped all four Valorant role icons so no neighboring symbol/artifact leaks into the asset.
- Removed the visible hard vertical cut in `/maps` artwork; map media now fades to the card background before the image ends.

### Changed
- Rebuilt the Overview `Map pool` from small decorative tiles into wide analyst rows with map thumbnail, record, win rate and pistol win rate.
- No match, roster, composition, event or historical data changed.

## v0.7.2 — Map artwork hotfix

### Changed
- Constrained `/maps` artwork to a fixed left-side zone instead of stretching it across the card.
- Shortened the fade so the image transitions into a clean solid surface before the right-side metrics.
- Kept expanded analytics on a fully uniform background.

### Data
- No database, match, roster, composition, event, or stat changes.

## v0.8.0 — Admin + deploy-ready data architecture

### Added
- Local-only `/admin` page for importing future official Tracker JSONs.
- Existing-series selector or new event/series creation from the admin form.
- Manual team-side fallback and borrowed-account canonical-name overrides.
- Duplicate `match_id` protection during admin imports.
- Precomputed per-map teamplay insight cache and full leaderboard cache.
- `scripts/prepare_deploy.py` and `PREPARE_DEPLOY_WINDOWS.bat` for one-step deploy database compaction.
- Root `main.py`, `.python-version`, `.gitignore` and deployment guide for Vercel/GitHub.

### Changed
- Hosted match pages and map analytics no longer depend on raw Tracker JSON being present in the public database.
- Public SQLite database reduced from roughly 182 MB to roughly 0.6 MB by caching required derived data and stripping raw payloads.
- Raw future admin imports are archived under `data/private_raw/` locally and excluded from Git.

### Vercel
- `/admin` returns 404 on Vercel intentionally; the hosted deployment is a read-only snapshot.
- Updating hosted data is: local admin import → prepare deploy → Git commit/push → automatic Vercel redeploy.

### Data
- No historical match result, roster assignment, composition, event, pistol or player stat was altered by this release.
