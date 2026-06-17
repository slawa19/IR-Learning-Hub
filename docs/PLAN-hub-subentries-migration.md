# Plan: Hub + config-subentries restructure (PR-MT)

> **Status: IMPLEMENTED & CONFIRMED on real HA (2026-06-17).** N=1 migration
> reshaped the legacy entry into hub+subentry, consumer entities survived without
> dupes, real sends produced physical device reaction; post-smoke `update_spec`
> refresh fix applied. Only file the migration mutates is
> `.storage/core.config_entries`; the store (`.storage/ir_learning_hub`, learned
> commands) is untouched — a full HA backup was not required. The design below is
> retained as the implementation reference.

## Why

The integration is conceptually **one hub** (a shared store of
`locations → devices → commands`) plus **N physical emitters** plus **M virtual
consumer devices**. The current model — *one config entry per transmitter* —
has no natural owner for the hub-level data, so we bolted on owner-election
(`consumer_owner`, `_entry_platforms`, re-election, `forwarded`), which produced
F1–F4 and the two lifecycle edges (disable-owner kills consumer entities;
remove-owner purges entity customizations).

The canonical HA model for "a hub managing several sub-devices that share a
common registry" is **one config entry (the hub) + config subentries (the
transmitters)**. It deletes the owner-election machinery and closes both
lifecycle edges by construction.

## Confirmed HA facts (verified 2026-06-17)

- Integrations declare subentry support via
  ```python
  @classmethod
  @callback
  def async_get_supported_subentry_types(cls, config_entry) -> dict[str, type[ConfigSubentryFlow]]
  ```
- Subentry flows extend **`ConfigSubentryFlow`** and support `user` +
  `reconfigure` steps (no discovery/reauth).
- Entities associate with a subentry via the add callback:
  ```python
  async_add_entities(new_entities, update_before_add=False, *, config_subentry_id: str | None = None)
  ```
  (`AddConfigEntryEntitiesCallback`); invalid id → `HomeAssistantError
  "Can't add entities to unknown subentry …"`.

### Spike-confirm before coding (verified against installed HA 2026.6.x in `.venv314`)
1. `ConfigSubentry` is a frozen kw-only dataclass with fields:
   `data`, `subentry_id`, `subentry_type`, `title`, `unique_id`
   (`homeassistant/config_entries.py:371-387`). `subentry_id` is auto-generated
   if omitted.
2. Main config flows support seeding subentries at creation time via
   `async_create_entry(..., subentries=[...])`
   (`homeassistant/config_entries.py:3387-3409`). There is **no**
   `hass.config_entries.async_create_subentry(...)` helper.
3. Programmatic subentry add/remove APIs are:
   `hass.config_entries.async_add_subentry(entry, ConfigSubentry(...))` and
   `hass.config_entries.async_remove_subentry(entry, subentry_id)`
   (`homeassistant/config_entries.py:2631-2654`).
4. Subentry flows use `ConfigSubentryFlow.async_create_entry(...)`; the flow
   manager materializes the returned result through `async_add_subentry(...)`
   (`homeassistant/config_entries.py:3668-3674`, `3681-3707`).
5. `device_registry.async_get_or_create(...)` accepts
   `config_subentry_id=` exactly with that name
   (`homeassistant/helpers/device_registry.py:880-904`).
6. Runtime reaction to subentry add/remove is straightforward: subentry changes
   go through `_async_update_entry(...)`, which fires the config entry
   `update_listeners` just like a normal entry update
   (`homeassistant/config_entries.py:2536-2629`). For v1, reloading the hub
   from the update listener is a supported/simple path.
7. Migration safety gate: the APIs above are all synchronous `@callback`
   methods on `hass.config_entries`, so calling `async_add_subentry`,
   `async_update_entry`, and `async_remove(...)` from component-level
   `async_setup(hass, config)` is event-loop safe. There is no specialized
   multi-entry migration helper; the migration must be an idempotent
   component-level reshape using these primitives.

## Target architecture (ownership map)

```
Config entry: "IR Learning Hub"  (single, hub)
├── owns: store, status sensor, services, consumer platforms
│         (remote / media_player / switch) + their virtual devices/entities
├── subentry (type "transmitter")  ieee=A
│     └── owns: emitter entity + emitter device (config_subentry_id)
├── subentry (type "transmitter")  ieee=B
│     └── owns: its emitter entity + device
└── …
```

- **Canonical transmitter key** stays `normalize_ieee(ieee)` (store key, emitter
  `unique_id`, device `transmitter_id`). Unchanged from PR3d.
- Virtual consumer device `DeviceInfo`: `identifiers={(DOMAIN,
  f"{loc}__{dev}")}`, `via_device=(DOMAIN, transmitter_key)` → nests under the
  emitter device. Unchanged.
- Emitter device: `identifiers={(DOMAIN, transmitter_key)}`,
  `via_device=("zha", ieee)`, associated to its subentry via
  `config_subentry_id`.

## Config-flow restructure (`config_flow.py`)

- **Main flow** = create the hub. Single instance: `async_step_user` aborts if
  already configured (`_async_current_entries`). To avoid an empty hub, the user
  step collects the **first transmitter** (reuse today's ZHA discovery / manual
  IEEE), creates the hub entry, and seeds its first transmitter subentry
  (mechanism per spike #1).
- `async_get_supported_subentry_types` → `{"transmitter": TransmitterSubentryFlow}`.
- **`TransmitterSubentryFlow`** (extends `ConfigSubentryFlow`):
  - `async_step_user`: ZHA discovery + manual IEEE (move the current
    `config_flow` discovery logic here). Subentry `unique_id =
    normalize_ieee(ieee)` → blocks duplicate transmitters.
  - `async_step_reconfigure`: edit `learn_timeout` / `learn_reassert_interval`.
  - Subentry `data`: `{ieee, profile, endpoint_id, cluster_id, learn_timeout,
    learn_reassert_interval}`.

## `__init__.py` restructure

**Remove (owner-election dies entirely):** `ENTRY_PLATFORMS`/`CONSUMER_PLATFORMS`
split, `consumer_owner`, `_entry_platforms`, `forwarded` tracking,
`_remove_entry_and_select_new_owner`, re-election in `async_unload_entry`,
per-entry `_async_remove_transmitter_for_entry`.

**`async_setup_entry(hass, hub_entry)`:**
1. Build singletons (store load, status, adapter, services) — once.
2. For each `transmitter` subentry: `store.async_upsert_transmitter_from_entry(
   subentry.data)`; register its emitter device with `config_subentry_id`.
3. `store.async_reconcile_transmitters({normalize_ieee(s.data[CONF_IEEE]) for s
   in transmitter subentries})` — drop orphans (now keyed off subentries).
4. Forward **all** platforms once: `[SENSOR, INFRARED, REMOTE, MEDIA_PLAYER,
   SWITCH]`.
5. Register an **update listener** for subentry add/remove → reload the entry
   (simplest; one entry, no owner election) OR diff emitters (decision: spike #3
   — recommend `async_schedule_reload(hub_entry.entry_id)` for v1).

**`async_unload_entry`:** unload all platforms; teardown services + `hass.data`.
Single entry → no re-election, no `forwarded`. Store file persists (data safe).

## Emitter platform (`infrared.py`)

- `async_setup_entry(hass, hub_entry, async_add_entities)`: iterate
  `hub_entry.subentries` of type `transmitter`; build one emitter per subentry;
  `async_add_entities([emitter], config_subentry_id=subentry.subentry_id)`.
- Emitter `unique_id`, `DeviceInfo`, `async_send_command` — unchanged from PR3d.

## Consumer platforms (`remote`/`media_player`/`switch`) — simplified

- Drop the owner gate (`if domain_data["consumer_owner"] != entry.entry_id`).
  They always set up on the hub entry. `ConsumerEntityManager`, feature
  resolution, trailing-edge reconcile, cleanup — all unchanged.

## Migration (the risky core)

**State today:** N config entries (each a transmitter, `entry.data` has
`ieee/profile/…`) + the shared `Store` (v4, keyed by `ieee`).
**Target:** 1 hub entry with N `transmitter` subentries. **Store is NOT touched**
— `transmitters`/`locations`/`commands` stay; `device.transmitter_id` canonical
keys remain valid.

**Where to run:** prefer a component-level `async_setup(hass, config)` (runs once
before entries set up) so we don't mutate sibling entries from inside one entry's
`async_setup_entry`. (Spike #4: confirm safe mechanics / consider
`async_migrate_entry`.)

**Algorithm (idempotent, guarded):**
1. Collect old-style entries: `domain` entries with `CONF_IEEE` in `data` and
   **no** `transmitter` subentries (not yet migrated).
2. If none → done (already hub-shaped).
3. Elect the hub = the oldest entry (stable by created/`entry_id`).
4. For the hub entry: add a `transmitter` subentry from its own
   `ieee/profile/...`; move those fields out of `entry.data` (hub data becomes a
   minimal marker, e.g. `{"hub": true}`).
5. For every **other** old entry: add a `transmitter` subentry to the hub from
   that entry's data, then `hass.config_entries.async_remove(other.entry_id)`.
6. Subentry `unique_id = normalize_ieee(ieee)` prevents duplicates if migration
   re-runs.

**Single-transmitter (the live case):** N=1 → that entry becomes the hub + one
transmitter subentry. Lowest complexity; must be exactly right.

**Guard / idempotency:** re-running must be a no-op (hub already has subentries,
old entries already removed). Never delete or rewrite the store.

## Backward compatibility

- All `ir_learning_hub.*` services unchanged (they operate on the store; the
  store and its API don't change).
- `transmitter_id` semantics unchanged (canonical key). Resolver/validation from
  PR3d unchanged.
- The status sensor + frontend card unchanged (card already lists transmitters
  via `list_commands`).

## Lifecycle edges — closed by construction

- **Disable a transmitter subentry:** only its emitter goes away; consumer
  entities live on the hub entry → unaffected. (Old disable-owner edge gone.)
- **Remove a transmitter subentry:** emitter + its device removed; consumer
  entities + their customizations stay on the hub. (Old remove-owner purge gone.)
- A consumer device whose `transmitter_id` pointed at a removed transmitter →
  `resolve_spec_transmitter` raises a clear `ServiceValidationError` (PR3d) — no
  silent breakage.

## Test plan

- Config flow: main flow creates hub + first transmitter subentry; subentry
  `user` flow adds a second; duplicate IEEE blocked by subentry `unique_id`.
- Setup: emitters created one-per-subentry (with `config_subentry_id`); consumer
  platforms on hub; reconcile drops orphan transmitters keyed off subentries.
- Subentry remove at runtime → emitter gone, consumer entities intact.
- **Migration (pure-ish, mock config_entries):** N=1 → hub+1 subentry, store
  untouched; N=2 → hub+2 subentries, one entry removed; re-run = no-op.
- Services + existing consumer/feature/transmitter tests stay green; delete the
  now-obsolete owner-election tests.

## Risk & rollback

- **Only file mutated = `.storage/core.config_entries`** (entry reshape + sibling
  removal). The store (`.storage/ir_learning_hub`, learned commands) is NOT
  touched, so the irreplaceable data is safe regardless. A full HA backup is
  unnecessary.
- **Safeguard:** copy `.storage/core.config_entries` before the upgrade restart
  (seconds). Migration is idempotent.
- **Rollback:** if reverting to old code, the hub-shaped entry won't be readable
  by it → restore the copied `core.config_entries`, OR simply remove + re-add the
  integration (learned commands persist in the store and reconnect by IEEE).
- Real-HA smoke required (single-transmitter migration path + send still works;
  add/remove a second transmitter subentry if UI is reachable).

## Resolved decisions (locked 2026-06-17)

1. **Migration runs at component-level `async_setup(hass, config)`** — once,
   before entries are set up — so we never mutate sibling entries from inside one
   entry's `async_setup_entry`. Idempotent + guarded. (Confirm the exact safe
   mechanics in the spike.)
2. **Single-instance hub:** `async_step_user` aborts if a hub entry already
   exists (`_async_current_entries`). One hub per HA instance.
3. **Seed the first transmitter in the main flow:** the user step collects the
   first transmitter (ZHA discovery / manual) and creates the hub entry with that
   first transmitter subentry — no empty-hub state. Further transmitters via the
   subentry `user` flow.
4. **Runtime emitter add/remove = `async_schedule_reload(hub_entry.entry_id)`**
   on subentry add/remove for v1 (one entry, cheap rebuild; no separate emitter
   diff-manager). Revisit only if reload proves disruptive.
5. **Subentry API is confirmed by a short spike against installed HA 2026.6.x
   before coding** (ConfigSubentry fields, create/add API, device_registry
   `config_subentry_id`) — same discipline as the infrared spike.

These are locked; the kickoff implements them. If the spike (5) reveals the
chosen mechanism for (1)/(3)/(4) is unsupported, stop and revise this doc rather
than improvising.
