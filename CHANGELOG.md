# BorderMargin V5.3.8

## UI / UX
- Unified model and web-research configuration surfaces.
- Content-sized status badges across the product.
- Refined cards, buttons, inputs, spacing, hover and focus states.
- Removed non-essential explanatory copy from AI/research settings.

## Decision Research Agent
- Rebuilt Decision Cases AI output as an interactive research workbench.
- Added Overview, Market, Pricing, Risks, Sources and Actions tabs.
- Added evidence coverage, market structure and pricing comparison charts.
- Added source filtering, expandable evidence, interactive action checklists and summary copy.
- Report language follows the current Chinese / English UI locale.
- Strengthened the research prompt for management-grade summaries, specific risks and prioritized actions.

## Tariff & Supply
- Rebuilt Global Tariff Reference Scan controls and progress presentation.
- Added current matrix count and clearer scan status.

## Runtime
- macOS startup now finds a compatible Python 3.11+ installation automatically.
- Old Python virtual environments are rebuilt automatically when too old.
- macOS startup reuses `/etc/ssl/cert.pem` for verified pip/requests HTTPS when available.
- Windows startup also rebuilds an outdated virtual environment and prefers Python 3.12 / 3.11.
- Node.js 22.12+ remains required on both platforms.

## Build
`v538-20260829-final-polish-r2`

## V5.3.8 final polish r2

- Decision Research now enforces the current UI language. Chinese projects request Simplified Chinese at planning and generation time; a localization pass automatically corrects a model response that returns in the wrong language while preserving facts, numbers, decision enums and source URLs.
- Origin-country supplier rows use responsive columns and safe overflow rules so the rightmost values no longer get clipped at narrower widths or browser zoom.
- Cost & Margin numeric inputs normalize floating-point display values. Percentage inputs such as 13.6% no longer surface binary artifacts such as 13.600000000000001; the same normalization applies to other editable cost/rate fields.
- Global tariff reference scan has a compact two-column control layout inside its narrower card and stacks progress content safely, eliminating clipped controls.
- Public version remains 5.3.8. Build: `v538-20260829-final-polish-r2`.

### Final layout polish
- Kept the eBay default marketplace field fully inside the data-source card at desktop and narrower widths.
- Rebalanced the four-column OAuth form and added safer responsive breakpoints.
