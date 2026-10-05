# Designing a tool against headless Aseprite

Every tool in this server is one run of `aseprite -b --script`. There is no window, no
canvas, no mouse and no plugin host, and the Aseprite scripting API does not say so: parts
of it are missing, parts return success and do nothing, two calls take the process down,
and one writes to the real user's configuration.

This file exists so that a constraint is discovered while an idea is being sketched rather
than three hours into implementing it. Read the table, then the section your idea lands
in. Every claim here is marked with how it was established; see
[What was re-verified](#what-was-re-verified-and-what-was-not) at the end.

## Check your idea in one pass

| If the tool needs to ... | Verdict | Do this instead |
| --- | --- | --- |
| use Aseprite's Shading ink | **Crashes** | Step palette indices yourself: [`tools/shading.py`](../src/aseprite_mcp/tools/shading.py) |
| use Aseprite's gradient tool | **Crashes** | Compute the gradient per pixel: `fill_gradient` in [`tools/effects.py`](../src/aseprite_mcp/tools/effects.py) |
| rotate, scale or skew a *region* | **No API** | Read pixels into an `Image`, transform, write back: [`core/inbetween.py`](../src/aseprite_mcp/core/inbetween.py) |
| flip or rotate the *whole sprite* | Works | `app.command.Flip` / `Rotate` with `target="sprite"` ([`tools/transform.py`](../src/aseprite_mcp/tools/transform.py)) |
| mirror half a layer onto the other | **Preferences do not apply** | Copy the pixels by hand: `mirror_layer` in [`tools/brushes.py`](../src/aseprite_mcp/tools/brushes.py) |
| rotate the contents of a selection | **Silent no-op** | Same manual route as a region transform |
| show a dialog, panel or progress bar | **Not usable** | Nothing to do. Return a structured result; the client is the UI |
| read or set the active editor, window or zoom | **Absent** | Take explicit coordinates as arguments |
| change a user preference | **Dangerous** | Take it as a tool argument. Never write `app.preferences` |
| scope an edit to a region across calls | Works, with care | The `.msk` sidecar in [`tools/selection.py`](../src/aseprite_mcp/tools/selection.py), and mask the write yourself |
| keep state between calls | **No** | Each call is a fresh process. Put the state in the file or in an argument |
| run a menu command | Sometimes | Check it is not in [section 2](#2-returns-success-and-does-nothing) below, then test it |
| use the frame `Sprite:newFrame(n)` hands back | **Returns the original** | Look the copy up as `spr.frames[n + 1]`: `copy_frame_after` in [`core/models.py`](../src/aseprite_mcp/core/models.py), and [section 7](#7-answers-that-are-not-what-they-look-like) |
| fill the pixels a Background gains (convert a layer, grow the canvas) | **Uses the editor's colour bar** | Set the colour first; the prelude already starts every script from the factory colours ([section 4](#4-present-and-must-not-be-touched)) |
| read an indexed sprite that has a Background | **Decodes wrong** in its own colour mode | Read Aseprite's RGB render: `readable_composite` in [`core/luagen.py`](../src/aseprite_mcp/core/luagen.py), and section 7 |

### The one-line test for "am I in batch mode"

`app.isUIAvailable` is `false` under `-b`. Guard on that, not on whether some interactive
global is nil: they have not all been removed, and `Dialog` in particular is still a
function (see section 3), so a nil check on it passes and tells you nothing.

## 1. Crashes the process

Exit code `0xC0000005`, no file written, and nothing useful on stderr. A tool built on
either of these does not fail, it disappears.

- `app.useTool{ink=Ink.SHADING}`
- `app.useTool{tool="gradient"}`

`Ink.SHADING` is a real value in the `Ink` table under `-b`, so the call looks available
and is reachable. That is the whole trap: a guard like `if Ink.SHADING then` passes.

**This is why ramp shading is palette index arithmetic.** Aseprite's Shading ink is the
right mechanic (shading in pixel art is stepping along a ramp, not adding brightness) and
it is unreachable, so [`tools/shading.py`](../src/aseprite_mcp/tools/shading.py)
reimplements it: match each pixel to its ramp entry by weighted RGB distance, then move
the index. The lighting geometry behind `specular_highlight`, `cast_shadow` and `glow`
lives in [`core/lighting.py`](../src/aseprite_mcp/core/lighting.py) for the same reason,
where it can be tested without an editor.

**This is why gradients are hand-rolled.** `fill_gradient` projects each pixel onto the
gradient axis, interpolates the stops and applies a Bayer 4x4 threshold itself, inside the
Lua body in [`tools/effects.py`](../src/aseprite_mcp/tools/effects.py).

## 2. Returns success and does nothing

The worst category, because a wrapper over one of these passes its own tests. The call
returns, the result says `ok`, and nothing happened.

| Call | Checked by |
| --- | --- |
| `app.command.Rotate{target="mask"}` | Re-verified: pixels and selection bounds both unchanged |
| `app.command.MaskContent` | Re-verified: pixels unchanged, and `app.transform` is nil, so there is no second step |
| `app.command.Timeline` | Re-verified: returned, sprite unchanged |
| `app.command.PlayAnimation` | Re-verified: returned, sprite unchanged |
| `app.command.Zoom` | Re-verified: returned, sprite unchanged |
| `app.command.Screenshot` | Re-verified: returned, sprite unchanged |
| `app.command.UndoHistory` | Re-verified: returned, sprite unchanged |
| `app.command.Scroll` | Re-verified: returned, sprite unchanged |
| Symmetry preferences, as an input to `app.useTool` | Taken on trust; see the end of this file |

Note what is *not* in this list: `Rotate{target="sprite"}` works, and is what
`rotate_sprite` uses. The target is the whole difference, which is exactly the kind of
distinction that makes a confident wrapper wrong.

**This is why mirroring is manual.** The symmetry that a human gets from the toolbar is a
preference consulted by the interactive tool loop, not an argument to the API.
`mirror_layer` and `draw_symmetric_pixels` in
[`tools/brushes.py`](../src/aseprite_mcp/tools/brushes.py) reflect coordinates and copy
pixels themselves.

**A related trap in the same family.** A selection clips `app.useTool` and the filter
commands, but *not* `Image:drawPixel`, which is what every drawing tool here goes through.
So the active mask has to be consulted by hand on every write; that is the `_sel` local in
the prelude in [`core/luagen.py`](../src/aseprite_mcp/core/luagen.py). Skip it and
selections appear to work for effects and are silently ignored for drawing, which is worse
than not supporting selections at all.

## 3. Absent under `-b`

There is no interactive or plugin surface. For the first six rows, reading the name gets
`nil` and calling a method on it is a Lua error inside your tool body. The last three rows
are the ones that do not behave that way, and they are the reason this section is a table
rather than a list.

| Name | Status under `-b` |
| --- | --- |
| `GraphicsContext` | nil |
| `Plugin` | nil |
| `Tool` | nil |
| `app.editor` | nil |
| `app.window` | nil |
| `app.transform` | nil |
| `app.site.editor` | the field does not exist (reading it raises, it does not return nil) |
| `Dialog` | **present as a constructor, and `Dialog{...}` evaluates to `nil`** |
| `app.site` | **present and populated** |

The last two rows correct [#96](https://github.com/MalloyTheDev/aseprite-mcp/issues/96),
which listed both as nil.

- `Dialog` being a function that builds nothing is more dangerous than `Dialog` being nil,
  because `type(Dialog) == "function"` and a truthiness guard both pass, and the failure
  then lands one line later on a nil value. Do not guard on the constructor; guard on
  `app.isUIAvailable`, or better, do not design an interactive tool.
- `app.site` reads fine: `sprite`, `layer`, `frame`, `frameNumber`, `cel`, `image`,
  `tilemapMode` and `tilesetMode` all return values once a document is open. Only
  `app.site.editor` is missing. Convenient, and still not a reason to depend on it: see
  section 6 on why "the active sprite" is a poor foundation here.

## 4. Present, and must not be touched

`app.preferences` exists under `-b` (it reads as `userdata`). **Writes to it persist to the
configuration of the human running this server.** A tool that sets a preference to get a
behaviour it wants changes how that person's Aseprite behaves afterwards, in their GUI,
permanently, and nothing in the result says so.

There is no safe wrapper here and no "restore it afterwards" version worth attempting: the
process can be killed on timeout between the write and the restore. Take the value as a
tool argument instead.

This is the one claim in this file that was deliberately **not** re-tested, because
testing it is the harm.

**The colour bar is a different case, and it was measured.** `app.fgColor` and
`app.bgColor` are the editor's state too, but here the trap is that a headless run *reads*
them. `BackgroundFromLayer`, and growing a Background with `Sprite:crop`, fill the new
pixels with the background colour, so the same call filled with `#a25ef6` at alpha 186 on
the machine this was found on, and with palette entry 4 of a 3-entry palette on an indexed
sprite. Writing them was tested before anything relied on it: one run set `app.bgColor` and
the next read it, and the second saw the editor's own colour, so a headless run does not
save the colour bar back. The prelude therefore starts every script from Aseprite's factory
colours (`data/pref.xml`, the `color_bar` section: a white foreground and a black
background). None of this is a licence to write `app.preferences`: the colour bar was
measured, and the rest of this section was not.

## 5. Possible, but only as manual pixel work

`app.transform` does not exist, and the `MaskContent` drag handles are a GUI affordance
(section 2). So region rotate, scale, skew and free transform have exactly one route:
read the pixels into an `Image`, transform them in code, write them back.

The repository already does this, and it is worth reading before writing a second copy:
[`core/inbetween.py`](../src/aseprite_mcp/core/inbetween.py) holds the transform matrix,
the whole-degree rotation snapping and the nearest-neighbour sampling behind `tween_cels`
and `smear_frame`. Two decisions in there generalise to any manual transform:

- **Sample from the original every frame, not from the previous frame**, so resampling
  error does not compound.
- **Nearest-neighbour, not interpolation.** An interpolated sample invents colours that
  are not on the palette, which is the difference between pixel art and a photograph of
  pixel art. For the same reason a rotation is snapped to whole degrees.

Whole-sprite operations are the exception and do not need any of this: `Flip` and `Rotate`
with `target="sprite"`, and `SpriteSize` for scaling, all work
([`tools/transform.py`](../src/aseprite_mcp/tools/transform.py)).

## 6. What does work, and what to build on

- Documents, layers, cels, frames, tags, slices, palettes and tilesets: the whole data
  model is available and is the right thing to drive.
- `Image:getPixel` / `drawPixel` and the prelude helpers in
  [`core/luagen.py`](../src/aseprite_mcp/core/luagen.py). Deterministic, and they do not
  care about a UI. **This is the drawing layer, and `app.useTool` is not.** Searching the
  source for `app.useTool` finds two comments and no calls: every pixel this server writes
  goes through an `Image`, which is why the crashes in section 1 and the symmetry
  preference in section 2 cannot be reached by accident. A new drawing tool that reaches
  for `app.useTool` is leaving the part of the API that was chosen deliberately.
- `app.command` for the non-interactive commands. These are the ones this server drives
  today, so the `--run-aseprite` tier already exercises them: `Flip`, `Rotate`
  (sprite target), `SpriteSize`, `NewLayer`, `MergeDownLayer`, `DuplicateLayer`,
  `LayerFromBackground`, `BackgroundFromLayer`, `LinkCels`, `UnlinkCel`, `ReverseFrames`,
  `ChangePixelFormat`, `ColorQuantization`, `MaskByColor`, `ModifySelection`, `InvertMask`,
  `SaveMask`, `LoadMask`, `ImportSpriteSheet`. Of those, the first four were re-run directly for this file as a
  control on the no-op probes.
- `app.range`, the timeline selection, which exists headlessly and is how cel linking is
  driven (see [`tools/cels.py`](../src/aseprite_mcp/tools/cels.py)).
- `app.fs`, `app.version`, `app.apiVersion`, `app.isUIAvailable`.
- Selections, through the `.msk` sidecar: Aseprite's own `SaveMask` and `LoadMask`
  round-trip a mask exactly, holes included, in well under a hundred bytes
  ([`tools/selection.py`](../src/aseprite_mcp/tools/selection.py)).
- A real GUI, if a human wants to watch. `open_in_editor` launches a detached Aseprite
  window and relies on its "file changed on disk" detection rather than trying to drive a
  window from a script ([`tools/gui.py`](../src/aseprite_mcp/tools/gui.py)).

**Do not build on the active document.** `app.sprite` is nil until something opens a
sprite, each tool call is a separate process, and no in-memory state (undo history, the
active layer, the active frame) survives between calls. Tools take explicit filenames,
coordinates and frame numbers for that reason. The selection sidecar is the single
deliberate exception, and it is deliberate state outside the sprite file: copying or
renaming a sprite leaves its selection behind.

## 7. Answers that are not what they look like

Neither crashes nor no-ops, which makes these the easiest to trust. Each was measured on
**2026-10-05** against Aseprite 1.3.18.6 (API 41), and the code that depends on each says
so where it does.

- **`Sprite:newFrame(n)` returns frame n, the original, not the copy.** The copy goes in at
  n + 1. The two are pixel-identical, so every colour check agrees with either story. A
  linked cel settles it: link frame n to a later frame, copy frame n, and the frame still
  sharing the original's image is n. Aseprite's source agrees (it pushes the requested
  frame number, not the inserted one). Take the copy as `spr.frames[n + 1]`:
  `copy_frame_after` in [`core/models.py`](../src/aseprite_mcp/core/models.py).
- **An indexed Background is drawn over its transparent index's colour.** That index is
  opaque there, a palette entry whose own alpha is 0 shows the base colour, and a
  half-transparent entry blends with it (`#0000c8` at 50% over `#0a141e` renders as
  `#050a73`). Decoding the indices yourself gets all three wrong; read Aseprite's RGB render
  instead, which is what `readable_composite` and `readable_layer` in
  [`core/luagen.py`](../src/aseprite_mcp/core/luagen.py) do, in that case only.
- **`ImportSpriteSheet` renders the cells onto a new, transparent layer.** On an opaque
  indexed sheet that turns everything drawn in the transparent index into "no pixel": a
  whole frame of the test sheet. Make the layer a Background again with the fill set to
  that same index, which rewrites those pixels with the value they already hold:
  `import_spritesheet` in [`tools/image.py`](../src/aseprite_mcp/tools/image.py). Aseprite's
  default fill painted them with an entry the palette did not have.
- **`Image:drawSprite` into an indexed image keeps every index**, 32 and above included,
  unlike `Image:drawImage` with the default blend mode (the reason for `BlendMode.SRC` in
  `get_draw_image`), so the composite readers do not suffer that loss.

## The binary is the source of truth, not the documentation

The shipped `data/gui.xml` next to the Aseprite executable declares **169 distinct
commands** (counted as distinct `command="..."` attribute values; there are 480
references to them across menus and shortcuts). The official scripting API documents a
small fraction of that, on the order of fifteen.

So the absence of a command from the documentation says nothing about whether it exists,
and its presence in `gui.xml` says nothing about whether it does anything under `-b`.
Both directions have to be tested, which is what the next section is for.

## Probing a claim yourself

Cheap, and it is how every re-verified claim in this file was established. Run a body
through the same path a tool takes:

```python
from aseprite_mcp.core.runner import run_lua

print(run_lua(r"""
    local spr = Sprite(16, 16)
    spr.cels[1].image:drawPixel(1, 1, app.pixelColor.rgba(255, 0, 0, 255))
    local before = spr.cels[1].image:getPixel(1, 1)
    local ok, err = pcall(function() app.command.SomeCommand() end)
    RESULT.returned = ok
    RESULT.error = ok and "" or tostring(err)
    RESULT.pixel_unchanged = (spr.cels[1].image:getPixel(1, 1) == before)
""", {}))
```

Three rules learned from doing it:

1. **Wrap the call in `pcall`.** Otherwise a Lua error aborts the script before `RESULT`
   is printed and you cannot tell "it raised" from "it crashed the process".
2. **Compare a fingerprint, not a return value.** "Returned without error" and "did
   something" are different facts, and section 2 is entirely made of calls where the first
   is true and the second is false. Hash the pixels, the frame count, the layer count and
   the dimensions before and after.
3. **Include a control in the same run.** `Rotate{target="mask"}` doing nothing only means
   something alongside `Rotate{target="sprite"}` changing the pixels in the same script.
   Without it you have measured your own harness.

## What was re-verified, and what was not

Re-verified on **2026-10-01**, against **Aseprite 1.3.18.6, API version 41**, on Windows,
through `aseprite_mcp.core.runner.run_lua` (that is, `aseprite -b --script`), on throwaway
sprites in a temporary workspace:

- Every entry in section 3's table, by reading `type(...)` of each name, and each
  `app.site` field in its own `pcall`.
- `Dialog` constructing `nil`, and the `Ink` table containing `SHADING`.
- `app.isUIAvailable` being `false`.
- `Rotate{target="mask"}` at 90 and 180 degrees: an L-shaped figure inside a 10x10
  selection was pixel-identical afterwards, the selection bounds were unchanged, and
  `Rotate{target="sprite"}` in the same script did change the pixels.
- `MaskContent` with a live selection: returned, pixels unchanged.
- All six UI commands in section 2: each returned, and the sprite's pixels, frame count,
  layer count and dimensions were unchanged.
- `Flip`, `Rotate` (sprite target), `SpriteSize` and `NewLayer`, as a control: all four
  returned, `NewLayer` added a layer and `SpriteSize` changed the dimensions. The rest of
  the commands in section 6 were not re-run here; they are covered by the `--run-aseprite`
  tier.
- The 169 commands in `data/gui.xml`, by counting distinct `command="..."` values in the
  shipped file.

Measured on **2026-10-05**, same build and route, for section 7 and the colour-bar
paragraph in section 4: each claim by the probe described beside it, the colour bar by one
run setting `app.bgColor` and the next reading it back.

**Taken on trust from [#96](https://github.com/MalloyTheDev/aseprite-mcp/issues/96),
on purpose:**

- The two crashes in section 1. The finding *is* the crash; reproducing a `0xC0000005`
  adds nothing and costs a lost process. What was re-checked is that `Ink.SHADING` exists,
  so the call is still reachable and the guard against it is still needed.
- `app.preferences` writes persisting to the user's configuration (section 4). Testing
  this means doing the harmful thing.
- Symmetry preferences not affecting `app.useTool`. Testing it requires writing
  `app.preferences`, so it falls under the same refusal. The architecture does not depend
  on the claim either way: mirroring is manual regardless.
- That the official API documents roughly fifteen commands. The denominator (169) was
  counted; the numerator was not.

Everything here is specific to a build. If a claim in sections 1 to 5 turns out to be
wrong on a newer Aseprite, that is a finding worth landing in this file with the version
it was measured on, not a reason to delete the workaround it explains.
