---
name: Contoso Digital Bank — Corporate Portal (PoC)
description: Minimal B2B corporate banking portal for a client showcase. Fluent UI v9 webLightTheme; this DESIGN.md names only the deltas and the PoC-specific components.
status: final
updated: 2026-09-30
colors:
  # Everything unlisted inherits Fluent v9 webLightTheme tokens.
  brand: '#0F6CBD'            # Fluent colorBrandBackground (inherited, named for reference)
  surface: '#FFFFFF'          # colorNeutralBackground1
  canvas: '#FAFAFA'           # colorNeutralBackground2 — page background behind cards
  stroke: '#D1D1D1'           # colorNeutralStroke1
  text: '#242424'             # colorNeutralForeground1
  text-muted: '#616161'       # colorNeutralForeground3
  success: '#107C10'          # colorPaletteGreenForeground1 — stage done, payment executed
  warning: '#BC4B09'          # colorPaletteDarkOrangeForeground1 — anomaly flag
  danger: '#C50F1F'           # colorPaletteRedForeground1 — rejected, blocked access
  synthetic-banner: '#FFF4CE' # colorPaletteYellowBackground1 — "Synthetic data" strip
typography:
  # Fluent v9 type ramp, Segoe UI. Inherited; listed for cross-reference only.
  title:    { fontFamily: 'Segoe UI', fontSize: 24px, fontWeight: '600', lineHeight: 32px }
  subtitle: { fontFamily: 'Segoe UI', fontSize: 20px, fontWeight: '600', lineHeight: 28px }
  body:     { fontFamily: 'Segoe UI', fontSize: 14px, fontWeight: '400', lineHeight: 20px }
  caption:  { fontFamily: 'Segoe UI', fontSize: 12px, fontWeight: '400', lineHeight: 16px }
  figure:   { fontFamily: 'Segoe UI', fontSize: 28px, fontWeight: '600', lineHeight: 36px }
rounded:
  sm: 2px
  md: 4px
  lg: 8px
  full: 9999px
spacing:
  '1': 4px
  '2': 8px
  '3': 12px
  '4': 16px
  '6': 24px
  '8': 32px
components:
  region-badge:
    background: '{colors.surface}'
    border: '{colors.stroke}'
    foreground: '{colors.text}'
    dot: '{colors.success}'
    radius: '{rounded.full}'
  stage-step-done:
    icon: '{colors.success}'
    foreground: '{colors.text}'
  stage-step-pending:
    icon: '{colors.text-muted}'
    foreground: '{colors.text-muted}'
  anomaly-flag:
    foreground: '{colors.warning}'
    radius: '{rounded.full}'
  synthetic-banner:
    background: '{colors.synthetic-banner}'
    foreground: '{colors.text}'
  kpi-card:
    background: '{colors.surface}'
    border: '{colors.stroke}'
    radius: '{rounded.lg}'
    value: '{typography.figure}'
---

## Brand & Style

This is a PoC for a client showcase, so it borrows Fluent's credibility rather than adding its own brand. It is the plain Microsoft Fluent v9 light theme, and anything that isn't a delta listed here is inherited unchanged. The only custom visual elements are the ones that tell the demo story: the region badge, the behind-the-scenes stage panel, anomaly flags and the synthetic-data banner. The look is calm and flat, the kind of internal banking tool a treasurer would trust.

## Colors

- **Brand blue `{colors.brand}`** is Fluent's own. It is used for primary buttons, the active nav item and links, and nothing else.
- **Success green `{colors.success}`** marks a completed medallion stage and an executed payment.
- **Warning orange `{colors.warning}`** is used only for anomaly flags. Orange means "the model thinks this is unusual".
- **Danger red `{colors.danger}`** marks rejected payments and the blocked-access message.
- **Synthetic banner yellow `{colors.synthetic-banner}`** is used for a single thin strip at the top of every screen. Clients take screenshots.
- There are no bronze, silver or gold hues on the stage panel. The stages are named in text and ticked in green, so the colour doesn't compete with the data.

## Typography

The Fluent v9 ramp in Segoe UI. `{typography.figure}` is used only for KPI values on the dashboard and for the balance in the account header.

## Layout & Spacing

The layout is desktop only, 1440×900, because the demo is on a laptop and a projector.
- **Chrome:** a fixed left nav of 240px and a top bar of 48px. The top bar holds the bank name, company switcher (read-only), region badge and user menu.
- **Content:** sits on `{colors.canvas}` with `{spacing.6}` gutters, and cards are laid out on a 12-column grid.
- **Behind-the-scenes panel:** a right-hand drawer, 360px wide.

## Elevation & Depth

Fluent's default: cards have shadow4 and the drawer has shadow16. Nothing else uses elevation.

## Shapes

Fluent defaults: `{rounded.md}` on controls and `{rounded.lg}` on cards. Badges and flags use `{rounded.full}`.

## Components

These Fluent v9 components are used as-is: `Button`, `Card`, `DataGrid`, `Input`, `Dropdown`, `Dialog`, `DrawerOverlay`, `Badge`, `MessageBar`, `Avatar`, `TabList`, `Spinner`, `Toast`. Charts are drawn as simple SVG line and area shapes in `{colors.brand}`.

PoC components:
- **Region badge:** a pill in the top bar reading "Serving from: West US 3", with a `{colors.success}` dot. It is always visible.
- **Stage panel:** a vertical list of steps: Ledger → Event Hubs → Bronze → Silver → Gold → Serving. Each step has an icon, a label and a timestamp. Completed steps use the done style, and later steps are muted.
- **Anomaly flag:** an orange warning icon plus the word "Unusual" in a `Badge`. Hovering shows the model's score and reason.
- **KPI card:** a caption label, a figure value and a delta line in body text.
- **Synthetic banner:** "Synthetic data — PoC environment", 24px high, full width.

## Do's and Don'ts

| Do | Don't |
|---|---|
| Use Fluent v9 defaults for everything not listed | Restyle Fluent components |
| Use orange only for anomalies | Use orange or red for ordinary negative balances |
| Keep the region badge visible on every screen | Hide the badge in a menu |
| Show the synthetic banner on every screen | Leave any screenshot without the banner |
| Use SVG sparklines and lines | Pull in a heavy charting library for a PoC |
