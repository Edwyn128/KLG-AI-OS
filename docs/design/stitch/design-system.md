---
name: Deep Space Intelligence
colors:
  surface: '#0f131c'
  surface-dim: '#0f131c'
  surface-bright: '#353942'
  surface-container-lowest: '#0a0e16'
  surface-container-low: '#181c24'
  surface-container: '#1c2028'
  surface-container-high: '#262a33'
  surface-container-highest: '#31353e'
  on-surface: '#dfe2ee'
  on-surface-variant: '#c4c6cd'
  inverse-surface: '#dfe2ee'
  inverse-on-surface: '#2c3039'
  outline: '#8e9197'
  outline-variant: '#44474c'
  surface-tint: '#b8c8de'
  primary: '#b8c8de'
  on-primary: '#233143'
  primary-container: '#1b2a3b'
  on-primary-container: '#8291a6'
  inverse-primary: '#516073'
  secondary: '#ffb3b3'
  on-secondary: '#680014'
  secondary-container: '#920121'
  on-secondary-container: '#ff9899'
  tertiary: '#b5c8df'
  on-tertiary: '#203243'
  tertiary-container: '#182a3b'
  on-tertiary-container: '#7f92a6'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#d4e4fb'
  primary-fixed-dim: '#b8c8de'
  on-primary-fixed: '#0d1d2d'
  on-primary-fixed-variant: '#39485a'
  secondary-fixed: '#ffdad9'
  secondary-fixed-dim: '#ffb3b3'
  on-secondary-fixed: '#400009'
  on-secondary-fixed-variant: '#920121'
  tertiary-fixed: '#d1e4fb'
  tertiary-fixed-dim: '#b5c8df'
  on-tertiary-fixed: '#091d2e'
  on-tertiary-fixed-variant: '#36485b'
  background: '#0f131c'
  on-background: '#dfe2ee'
  surface-variant: '#31353e'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '600'
    lineHeight: 32px
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Inter
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  label-md:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.05em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '700'
    lineHeight: 14px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  container-padding: 24px
  panel-gutter: 12px
  component-gap: 8px
  list-item-padding: 12px 16px
---

## Brand & Style

This design system is engineered for high-stakes, data-intensive professional environments where clarity, authority, and technical precision are paramount. It adopts a **Corporate Modern** aesthetic infused with a **SaaS/Developer** edge, characterized by high information density and a "command center" atmosphere.

The visual narrative is built on stability and intelligence. It utilizes a dark, monochromatic foundation punctuated by sharp accent lines and glowing state indicators to guide the user's attention through complex workflows. The emotional response is one of calm control—minimizing eye strain during long sessions while projecting a premium, institutional reliability through its deep color palette and structured geometry.

## Colors

The palette is anchored by the **Dark Navy (#080C14)** base, providing a near-black canvas that reduces luminance. UI surfaces are tiered using **Slate (#2C3E50)** and **KLG Navy (#1B2A3B)** to create structural separation without relying on heavy borders.

**Key Accents:**
- **KLG Red (#B22234):** Reserved for high-urgency states and strategic brand markers, such as the signature horizontal gradient line.
- **KLG Navy (#1B2A3B):** Used for primary interactive backgrounds and active selections.
- **Amber Glow (#F39C12):** Specifically utilized for "Overdue" status indicators to provide a distinct, high-visibility contrast against the cool-toned base.

The design features a signature **Linear Gradient** (Navy to Red) that serves as a structural separator, reinforcing the brand's identity at key layout intersections.

## Typography

The system utilizes a dual-font strategy to balance human-centric readability with technical precision.

- **Inter** handles all primary interface elements, headings, and body content. Its neutral, high-legibility profile ensures that dense legal or financial data remains scannable.
- **JetBrains Mono** is employed for metadata, identifiers (e.g., "Matter 2023-A4"), and status labels. This monospaced choice reinforces the "OS" aesthetic and provides clear character differentiation for alphanumeric strings.

Typography is tightly tracked in headers to maintain a compact, professional footprint. Body text uses a slightly relaxed line height to ensure legibility against the dark background.

## Layout & Spacing

The layout follows a **Fixed Grid** philosophy for the sidebar and utility panels, while the central workspace remains **Fluid** to accommodate varying lengths of chat dialogue and data visualizations.

- **High Density:** Padding is kept tight to maximize the "at-a-glance" information density.
- **Panel System:** The UI is divided into distinct functional zones (Navigation, Workspace, Utilities) separated by subtle 1px borders or slight tonal shifts.
- **Horizontal Separator:** A 2px gradient line (Navy to Red) provides a definitive horizontal break between the global header and the functional workspace.

## Elevation & Depth

This design system avoids traditional drop shadows in favor of **Tonal Layers** and **Inner Glows**.

- **Surface Tiers:** Backgrounds move from darkest (Base) to lighter (Panels) to lightest (Active items/Popovers).
- **Luminous Depth:** Interactive elements, like the Overdue badges, utilize an outer glow (Amber) rather than a shadow. This creates a "self-illuminated" effect common in head-up displays (HUDs).
- **Subtle Borders:** 1px borders in slightly lighter shades of Navy/Slate define the edges of containers, maintaining a flat but structured appearance.

## Shapes

The design system uses a **Soft (0.25rem)** roundedness for standard components like input fields and chat bubbles. This provides a modern touch without sacrificing the serious, professional tone of the product.

Larger containers (Panels) utilize **rounded-lg (0.5rem)** to softly frame the workspace content. Status badges and tags may occasionally use pill shapes for maximum differentiation from the predominantly rectangular structural elements.

## Components

### Overdue Badges
These are the most high-contrast elements in the system. They feature a dark container with a prominent left-side amber border and a diffused amber outer glow. The text is a combination of bold sans-serif for the status and monospaced for the metadata.

### Chat Bubbles
Bubbles are differentiated by tonal shifts. User messages use a slightly lighter slate (#2C3E50), while AI responses use a deeper navy background. They feature minimal padding and sharp corners with subtle rounding to maintain the high-density aesthetic.

### Sidebar Nav
Items use a transparent background by default. On hover or selection, they transition to a Navy (#1B2A3B) background with a high-contrast left-side accent bar (KLG Red or Bright Blue) to indicate focus.

### Input Fields
The primary command input is a dark, recessed field with a thin Slate border. The "Send" button is integrated directly into the field's container, using the Navy (#1B2A3B) primary color.

### Action Bar
Located at the bottom of the workspace, it houses low-profile icons for attachments and system settings, using ghost-style buttons that only reveal their container on hover.
