# The patch bay

The Patch bay view of a strategy tab draws the strategy graph as modules on a canvas,
linked by cables. It is one of two editors of the same graph: the Code view is the other.

- **Source of truth.** Every edit makes a new `StrategyGraph` (`titanium/core/patchbay.py`)
  and puts it through `Workspace.strategies`. The Code view and the Knobs dock follow;
  edits typed in the Code view redraw the canvas.
- **Modules** show their input ports on the left, output ports on the right and their knobs
  below (drag a slider, click a switch). Double-click a module's title to see its code.
- **Cables** go from an output to an input: drag from an output port and drop on an input
  (anywhere on the input's row will do). Drag a plugged cable off its input to move or
  unplug it. Links that can't be made are refused with the reason: the input is already
  taken, it would make a loop, or a module would feed itself.
- **Right-click** the canvas to add a module, tidy or fit; a module to rename, show its code,
  unplug, duplicate, save it to your module library or remove it; a cable to unplug it.
- **Keys**: Delete removes the selection, Ctrl+Z / Ctrl+Shift+Z undo and redo (edits made on
  the canvas; a change in another view clears the redo list), Ctrl+D duplicates, Ctrl+A
  selects all, Ctrl+0 fits, Ctrl+= and Ctrl+− zoom. The wheel zooms at the cursor; middle-drag
  or Space and drag pans; drag on empty canvas to select a group.
- **Positions** are saved in each `Module.layout`. Modules added in code (with no position)
  are placed to the right of the others until you move them.

## The Module library dock

A tree of folders: the app's **Starter** folder, your own folders, and folders added by
plugins, with search over names and descriptions. Drag a module onto the patch bay, or
double-click it, to add it to the strategy in front.

Your folders are directories under `Documents/Titanium/modules` (`paths.app_folder()`), one
JSON file per module (`titanium/app/module_folders.py`, `Workspace.modules`). Make, rename and
delete folders, and rename, move (drag onto a folder) or delete your modules. Starter and
plugin modules can't be changed, only copied into your folders. Right-click a module on the
canvas and pick *Save to module library* to keep your own version of it.

## The kit

The canvas is built from `NodeCanvasScene` and `NodeCanvasView` in
`titanium/desktop/design/node_canvas.py` (shown in the gallery), inside
`Canvas(backdrop=False)`; the view draws the skin's backdrop itself so it pans and zooms.
