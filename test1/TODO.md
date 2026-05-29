# TODO

Deferred work items (not blocking; pick up when convenient).

## UI / GUI

- [ ] **Surface the changelog directly in the Schematic Generator tab**, under the
      Regenerate button (and above the Linter checklist). The user should be able to
      ADD to and VIEW the changelog from the Generator tab itself — not only from the
      Agent rail. Reuse the existing add/view/delete/clear logic from
      `AgentRail.tsx` → `ChangelogPanel` (extract it into a shared component so both
      places stay in sync). The Agent rail (AI chat) must stay UNCHANGED and identical
      across all tabs — chat is the only thing that lives there now.

- [ ] **Collapse the changelog into a dropdown when it has more than 3 bullets**,
      like the Linter checklist (show a count + expand/collapse). Under 3 stays
      expanded inline. Applies to the shared ChangelogPanel.

## Simulation → changelog flow

- [ ] **Reflect sim suggestions in the UI the moment they're added to the changelog,
      and mark them PENDING until applied.** In the Simulation window, when a suggested
      change is added to the changelog (the "Add to changelog" action on an interpret
      SUGGESTION), the suggestion's row should immediately update to a "added / pending"
      state (not stay as a fresh, un-actioned suggestion). The corresponding changelog
      item stays flagged **pending** until the apply pass actually implements it (then
      it clears / shows applied). I.e. give sim-originated changelog items a lifecycle:
      suggested → pending (in changelog) → applied. Ties into the existing
      source="sim" + sim_block/sim_type tagging and the decisions.json
      (APPLIED/STOPPED/CLARIFY) outcome record so "applied" can be detected reliably.
