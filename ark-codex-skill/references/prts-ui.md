# PRTS Model Viewer Reference

Operator pages live at `https://prts.wiki/w/<Operator>`.

## Loading the viewer

- Find the button with text `点此载入模型` and click it.
- Wait for the model widget to appear.

## Widget controls

The widget uses Naive UI. The three relevant selects are `.n-select` elements:

1. `时装组` (skin group): options include `默认` and skin names.
2. `模型组` (model group): options are `战斗` and `基建`.
3. `动画` (animation): options include `Default`, `Interact`, `Move`, `Relax`, `Sit`, `Sleep`.

Some models also advertise `Special`. The exporter probes it after the base actions; if absent it closes the dropdown and continues, but a present action's download failure is reported. Do not assume every operator has Special.

To change a select:

1. Click the `.n-select` element.
2. Click the matching `.n-base-select-option` item.
3. Wait ~1 second for the model to reload.

## WebM export

- Find the icon button whose SVG path contains `M19 9h-4V3H9v6H5l7 7l7-7z` (a download icon).
- Click it and wait for the browser download event.
- The exported file is a WebM animation. Suggested filenames look like
  `浊心斯卡蒂-默认-基建-Interact-x1.webm`.
- Default is often a broken 110-byte file. A broken supplied Special file must be reported, not silently ignored.

## Search API

Resolve an operator title with the MediaWiki API:

```text
https://prts.wiki/api.php?action=query&list=search&srsearch=<operator>&srlimit=20&format=json&formatversion=2
```

Prefer an exact title match, then a title containing the operator name.
