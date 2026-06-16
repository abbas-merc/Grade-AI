/**
 * constants/theme.ts — Centralised design tokens for GradeAI.
 *
 * COLORS / RADIUS / SPACING / FONT are the canonical palette and scale used by
 * every screen and component. ON holds the accent text/background shades that
 * pair with the tinted "*Light" backgrounds — kept here so that no raw hex
 * colour strings live in any component or screen file.
 */

export const COLORS = {
  primary: '#1B4DFF',
  primaryLight: '#E6EDFF',
  surface: '#F7F8FA',
  card: '#FFFFFF',
  border: '#E4E4E0',
  textPrimary: '#1A1A1A',
  textSecondary: '#6B6B68',
  textTertiary: '#9B9B97',
  pass: '#27B468',
  passLight: '#EAF3DE',
  fail: '#E24B4A',
  failLight: '#FCEBEB',
  warning: '#F59E0B',
  warningLight: '#FAEEDA',
}

export const RADIUS = {
  sm: 6,
  md: 10,
  lg: 12,
  xl: 16,
}

export const SPACING = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
}

export const FONT = {
  regular: '400' as const,
  medium: '500' as const,
}

/**
 * Accent shades used as text/badge colours on the tinted "*Light" backgrounds.
 * Centralised here so component stylesheets stay free of raw hex strings.
 */
export const ON = {
  primaryText: '#0C447C',   // text on primaryLight (chips, feedback)
  passText: '#27500A',      // score badge text, percentage >= 70
  warningText: '#633806',   // score badge text, 50–69
  failText: '#791F1F',      // score badge text, < 50
  deleteText: '#A32D2D',    // delete action text on failLight
  extendedBg: '#F1EFE8',    // "Extended" tier badge background
  extendedText: '#444441',  // "Extended" tier badge text
}
