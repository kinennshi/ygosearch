# UI assets

`card-back.jpg` is copied unchanged from the local YGOPro2 source:
`Assets/old/Ocgcore/card/Materials/back_pic.jpg`.
Upstream: https://github.com/duelists-unite/YGOPro2
Yu-Gi-Oh card imagery belongs to its respective rights holders.

`attribute/` and `race/` contain 7 attribute and 26 race icons copied unchanged
from https://github.com/SethPDA/MDPro3 at commit
`1d106cc4919f6996209215441035781f6f85203b`.
Individual source paths are recorded in `icon-sources.json`. Mappings were
verified against Unity GUID references in `TextureContainer.asset` and the
upstream `TextureManager.GetCardRaceIcon` / `GetCardAttributeIcon` methods.
These game images retain their original rights; the upstream project license
does not imply ownership of Konami's game artwork.

`card-theme.css` is the YGOSearch presentation layer. Existing dimensions,
spacing, and responsive breakpoints remain in `web/index.html`. Icons fit
inside the existing chip padding; Chinese labels remain visible.

`kind/` contains MDPro3 card-type, Pendulum, and Spell/Trap subtype icons from
the same pinned commit. Spell/Trap glyphs and the Pendulum icon are matched
through `TextureContainer.asset` GUIDs. Numbered card-type icons were visually
checked: monster, spell, trap, fusion, synchro, xyz, link. Normal and Ritual
monster icons use CSS color variants of the monster card silhouette; the PNG
is unchanged. Labels always remain visible.

Frame reference: `kooriookami/yugioh-card`,
`src/assets/yugioh-card/yugioh/image/card-effect.png`:
https://github.com/kooriookami/yugioh-card
The square outer frame, bevelled name strip, and pale effect panel with corner
plates are recreated in CSS. The reference pendulum template is retained below.
Result descriptions have 10px vertical and 12px horizontal padding, 13px type,
and 1.75 line height. An inner text container clamps at five complete lines, separate from the
outer padding; expanded text has no maximum height. Page columns, responsive breakpoints, and interactions remain
unchanged.

Ban-list filter: `ban/forbidden.png`, `limited.png`, `semi-limited.png` are
unchanged MDPro3 `GUI_T_Icon1_Limit00/01/02.png` from the pinned commit above.
`ban/unlimited.svg` is an original matching green 3-copy indicator; it is not
an upstream/official asset. No dedicated Unlimited icon was found there.
`kind/pendulum-card.png` is the unchanged standard OCG template
`src/assets/yugioh-card/yugioh/image/card-effect-pendulum.png` from
https://github.com/kooriookami/yugioh-card (master, retrieved 2026-10-03),
retained as a reference. The displayed `kind/pendulum-card.svg` is an original
miniature with an explicit central artwork frame and brown/green card panels.
Search/Card and effect-type filter chips share an 88 × 32 CSS pixel size; only
chip rows wrap. Scrollbars use the same muted gold and parchment palette.
