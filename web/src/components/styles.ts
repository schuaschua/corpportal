import { makeStyles, tokens } from '@fluentui/react-components';

// DESIGN.md deltas on top of webLightTheme. Everything else is Fluent's default.
export const colors = {
  brand: tokens.colorBrandBackground,
  success: '#107C10',
  warning: '#BC4B09',
  danger: '#C50F1F',
  muted: tokens.colorNeutralForeground3,
  stroke: tokens.colorNeutralStroke2,
  synthetic: '#FFF4CE',
};

export const useShared = makeStyles({
  card: {
    padding: '16px',
    borderRadius: tokens.borderRadiusXLarge,
    boxShadow: tokens.shadow4,
    backgroundColor: tokens.colorNeutralBackground1,
  },
  cardTitle: {
    fontSize: tokens.fontSizeBase300,
    lineHeight: tokens.lineHeightBase300,
    fontWeight: tokens.fontWeightSemibold,
    margin: '0 0 12px',
  },
  h1: {
    fontSize: tokens.fontSizeBase600,
    lineHeight: tokens.lineHeightBase600,
    fontWeight: tokens.fontWeightSemibold,
    margin: '0 0 4px',
  },
  sub: { color: colors.muted, margin: '0 0 20px' },
  headRow: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '16px' },
  tip: { fontSize: tokens.fontSizeBase200, lineHeight: tokens.lineHeightBase200, color: colors.muted },
  num: { textAlign: 'right', fontVariantNumeric: 'tabular-nums', justifyContent: 'flex-end' },
  stack: { display: 'flex', flexDirection: 'column', gap: '16px' },
  message: { marginBottom: '16px' },
});

export const useLegend = makeStyles({
  legend: { display: 'flex', gap: '16px', fontSize: tokens.fontSizeBase200, color: colors.muted, marginTop: '8px' },
  item: { display: 'inline-flex', alignItems: 'center', gap: '6px' },
  swatch: { display: 'inline-block', width: '16px', height: '2px', backgroundColor: colors.brand },
  dashed: {
    backgroundImage: `repeating-linear-gradient(90deg, ${tokens.colorBrandBackground} 0 4px, transparent 4px 7px)`,
    backgroundColor: 'transparent',
  },
  threshold: { backgroundColor: colors.danger },
});
