# LED profile clip for the rack dividers

[`led_profile_divider_clip.scad`](led_profile_divider_clip.scad) is a parametric PETG clip that
snaps over a 37 mm square wooden divider set corner-up (45°) and holds a 16 × 16 mm aluminium
corner LED profile in a slide-in channel on top. Open it in OpenSCAD, set `part`, press F6 and
export the STL.

![assembly](clip_preview.png)

![cross-section](clip_section.png)

## How it works

- **Saddle:** a 2.5 mm band that follows the divider's two upper faces. Its hooks reach
  `grip_depth` (2.5 mm) below the divider's side corners, so the clip clicks on when pushed
  straight down. The upper faces act as the lead-in ramp.
- **Channel:** a concave 90° V that the profile's two 16 mm backs nest in. Two lips hook
  `lip_overlap` (1.2 mm) over the profile's front edges, so the profile slides in from the end
  and cannot lift out. Two crush ribs run along the channel and add a 0.15 mm interference so
  the profile stays put.
- **Aim:** `aim_angle` tilts the channel about the profile's back corner. 0 points the diffuser
  straight up, ±30 points it towards the front or back of the rack.

## Default size

| | |
|---|---|
| Length along the divider | 15 mm |
| Height above the divider's top corner | about 21 mm |
| Width across the divider | about 60 mm |

## Fitting

1. Print one clip and test it on the wood and on the profile before printing the rest.
2. Push the clips down over a divider, about every 150–200 mm (two per 95 mm bin is more than
   enough).
3. Slide the profile through all the clips from one end.

## Tuning

| Parameter | Default | Change it when |
|---|---|---|
| `divider_side` | 37.0 | the real wood measures differently |
| `divider_clear` | 0.4 | the clip is too tight or loose on the wood |
| `grip_depth` | 2.5 | the clip is too hard to push on (lower) or falls off (raise). 0 = no hooks |
| `profile_tol` | 0.3 | the profile slides too stiffly or rattles |
| `crush` | 0.15 | the profile slips (raise) or won't go in (lower, or 0) |
| `lip_overlap` | 1.2 | the diffuser bulges out under the lips (lower) |
| `aim_angle` | 0 | you want the light aimed forwards or backwards |

## Print notes (PETG)

Print as modelled, with one end face on the bed. Every layer then holds the whole cross-section,
so the hook arms flex within a layer, which is their strong direction. No supports are needed.
Use 0.2 mm layers and 4 perimeters; 100 % infill is cheap at this size and makes the hooks tougher.

## Assumptions

The profile is assumed to be a 90° **corner** profile: two flat 16 mm backs at a right angle,
with the diffuser across the open side. If yours is a different shape (for example a
half-round with a flat base), the channel needs a different pocket. Everything else stays.
