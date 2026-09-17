# SD card manager implementation brief

Implement the pending **Manage SD Card** feature in the base Settings screen.

## User-visible behavior

- In the inline `[ Device ]` section of Settings, show `MANAGE SD CARD` above
  `SOFT RELOAD` only when the microSD is mounted and writable.
- Opening it shows a separate `SD CARD` page with a fully expanded tree rooted
  at `/sd` (the simulator root is `.simulator`). Do not hide dotfiles or any
  other names: configuration, logs, framebuffer scratch files, and all other
  managed files must be visible.
- Expand directories through depth 3 inclusive. If a directory at that depth
  contains entries, render one non-focusable child line:
  `... lower levels trimmed ...`.
- Limit the complete rendered tree to 50 real files/directories. If there are
  more, append the non-focusable line `... other items not shown ...`.
- Render indentation and a directory marker so tree structure is clear. Sort
  deterministically (directories first, then case-insensitive name) so focus
  does not jump between renders.
- Back/left returns to Settings and restores the previous Settings focus.
  Up/down, the third/fourth footer buttons, and side buttons navigate only
  focusable file/directory rows. Use a viewport and a compact scrollbar when
  the focused list exceeds the rows available on screen.
- Footer labels on this page: `Back`, `Delete`, `v`, `v`. `Delete` is only
  actionable for a focused real item.
- Delete opens a modal drawn over the tree. It names the selected item and
  asks for confirmation. While open, labels are `Back`, `Delete`, ``, ``;
  only Back dismisses and Delete confirms. All direction/side inputs do
  nothing.
- Confirming a file removes it. Confirming a directory recursively removes
  every descendant and then the directory. Never permit deleting the root
  itself or a path outside the configured SD root. Refresh the tree and move
  focus to the nearest surviving item.
- If the SD disappears during browsing or deletion, abandon the manager,
  enter the existing read-only/no-SD mode, and show the Home warning. Never
  fall back to internal flash.

## Architecture guidance

- Put path validation, bounded tree construction, directory detection, and
  recursive removal in a small SD-storage helper, not in UI code.
- Keep CircuitPython compatibility: no `pathlib`, `typing`, desktop-only
  dependencies, or broad exception suppression in device files.
- Use the existing `Navigation` stack for the manager route so normal Back
  restores Settings focus. Long Back must continue to clear history and go
  Home.
- Keep rendering and button state in a focused manager controller or a
  purpose-built BaseUI method; do not overload generic Settings actions with
  a fake flat list.
- The simulator should exercise the same manager/controller behavior. Its
  SD root is `xbrut/simulator`'s existing `.simulator` data directory. Add an
  explicit simulator action/button if needed to enter the manager, but do not
  make simulator-only filesystem behavior leak into device code.

## Required x64 tests

Add thorough deterministic unit tests. At minimum cover:

1. Tree ordering, indentation, file versus directory rows, and inclusion of
   dotfiles.
2. Exact depth-3 trimming behavior.
3. Exact 50-real-item cap plus the non-focusable overflow row.
4. Empty root and nested empty directories.
5. Focus navigation skips informational rows; viewport/scrollbar changes as
   focus crosses visible bounds.
6. Back restores the Settings focus saved before opening the manager; long
   Back clears history to Home.
7. Modal input isolation, cancellation, and delete confirmation.
8. File deletion, recursive directory deletion, and focus selection after
   deletion.
9. Rejection of root deletion, traversal (`..`), and paths outside the SD
   root.
10. SD removal/failure during list and deletion transitions to read-only mode
    without writing internal flash.
11. Simulator operations use a temporary simulator-root fixture and really
    remove the expected file/directory, never repository files.

Run `tools/validate.sh` (with a workspace `TMPDIR` when required), inspect
the diff for forbidden flash fallbacks, then commit and push directly to
`main`. Deploy to `/dev/ttyACM0` and smoke-test when it is available.
