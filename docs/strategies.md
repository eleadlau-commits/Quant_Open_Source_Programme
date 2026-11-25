# Strategies page: tabs, the default strategy, closing and deleting

## Adding a strategy

There is one way in: the **New strategy** button in the page header. Its menu has
New empty strategy, From the strategy library (Phase 2), Import a Python file, and Open a
strategy file. Right-click a tab for Save (Ctrl+S), Rename, Duplicate, Close and Delete.

## The default strategy

The **Default** tab is always open, on the left. It is the default strategy
(`core/default_strategy.py`): equal weight in everything in the dataset, put back to equal
each month. It runs like any strategy, its knobs turn, and its run settings change, but its
logic is read-only (`PatchBay.set_locked`, `CodeView.set_locked`). **Duplicate to edit** opens
an editable copy. It can't be closed, moved off the left, or deleted.

The yardstick that Compare and the backtests measure every run against is still
`core/baseline.HoldEverything`, so turning the Default tab's knobs never moves the yardstick.

## Ids and names

A strategy's id is a hidden key (`s-` plus 8 hex digits, `Workspace.new_strategy_id`). It is
never shown and never reused, because runs and backtest results record it: a new strategy
must never pick up an old one's results. Files saved before this change keep their `S1`-style
ids and still open.

The name is what tabs show. A new strategy is called "Strategy N" with the lowest N no
open strategy uses (`Workspace.new_strategy_name`), and can be renamed.

## Closing and deleting

- **Close** (the tab's ✕) closes the tab. If the strategy changed since it was opened or saved,
  it asks to save first. Its runs stay for the session, so opening its file again brings them
  back (same id).
- **Delete** (right-click the tab) removes the strategy for good, after a confirmation that says
  what goes with it. `Workspace.delete_strategy` cancels its runs and tests still going, removes
  its runs and their backtest results, and frees its data. A run or test of it that finishes
  later is dropped. The default strategy's yardstick runs are shared by every strategy and stay.
  The saved file is deleted only if that box is ticked.
