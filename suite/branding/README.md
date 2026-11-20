# OpenGeul Office runtime branding

`runtime_branding.py` accepts an authenticated, extracted runtime root and creates
an absent destination such as `payload/Office`. It patches real registry/INI/UI
files and image archives, preserves original legal files and executable bytes,
and records before/after hashes in `opengeul-branding.json`. The package builder
must record the official archive SHA-256, exact OpenGeul source commit and source
bundle separately. A receipt does not establish Windows GUI qualification.

`mark.svg` and `logo.svg` are original OpenGeul artwork under this repository's
MIT license. No font file is included. PNG artwork is rasterized from these SVGs;
`logo_inverted.svg`, `logo-sc.svg`, `logo-sc_inverted.svg`, `about.svg` are complete
branding inputs rather than omitted files that fall back to upstream logos.

The extracted-runtime overlay changes the product and factory names, a distinct
`$SYSUSERCONFIG/OpenGeul/Office/4` default profile, Start Center labels, translatable
UI XML references, splash/wordmark artwork and Start Center module icons. It
disables upstream binary and extension update URLs. The worker additionally uses
a separate temporary profile for each owned document process. HWP/HWPX and UNO
factory/service/filter identifiers remain unchanged. Math and Base keep their own
native UI; only Writer/Calc/Impress/Draw have a Tabbed preset.

For a source build, substitute the absolute artwork directory for
`@OPENGEUL_BRANDING_DIRECTORY@` in `autogen.input.in`, then pass the resulting
lines to the matching upstream revision's `autogen.sh`. Do not use a headless or
GUI-disabled build for the Windows Suite. Apply the display-label changes to:

- `officecfg/registry/data/org/openoffice/Setup.xcu`: product and factory UI names;
  `officecfg/registry/data/org/openoffice/Office/UI/ToolbarMode.xcu`: presets.
- `sfx2/uiconfig/ui/startcenter.ui` and other translatable `.ui` text.
- `include/svtools/strings.hrc`, `include/sfx2/strings.hrc`, `cui/inc/strings.hrc`
  and matching `translations/source/{en-US,ko}/` catalog text where applicable.
- `instsetoo_native/util/openoffice.lst.in` and
  `instsetoo_native/CustomTarget_setup.mk`: installer names, installation/profile
  roots and update metadata. Keep internal UNO/file-format identifiers.
- `sysui/desktop/icons/soffice.ico` and each module `*_app.ico`, consumed by
  `desktop/WinResTarget_*.mk`, plus `sysui/desktop/share/` launcher names.

The post-extraction overlay deliberately does **not** rewrite signed PE resources,
file descriptions or embedded executable icons. A complete replacement of those
surfaces requires the source build above and fresh signing. Help, compiled native
strings and localized catalogs need a complete UI audit before claiming every
surface is branded. Copyright, license and derived-from notices remain intact.

Official references: [configure branding hooks](https://github.com/LibreOffice/core/blob/3ff15b221a48ae5588cf8dee7013a0cafe99f054/configure.ac),
[factory labels](https://github.com/LibreOffice/core/blob/3ff15b221a48ae5588cf8dee7013a0cafe99f054/officecfg/registry/data/org/openoffice/Setup.xcu),
[MPL distribution FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/).

Reproduce bitmap assets with Inkscape (using the installed system sans-serif font):

```sh
inkscape logo.svg --export-width=440 --export-filename=intro.png
inkscape logo.svg --export-width=880 --export-filename=intro-highres.png
inkscape mark.svg --export-width=32 --export-filename=icon-32.png
inkscape mark.svg --export-width=128 --export-filename=icon-128.png
```

`donate1.png` and `donate2.png` use the original document mark as artwork. Their
presence prevents fallback to the default supplier's artwork, without redirecting
any donation button or altering legal credits.
