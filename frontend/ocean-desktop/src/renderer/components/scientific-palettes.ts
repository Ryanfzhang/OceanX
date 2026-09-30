export const OCEAN_TEAL = ['#F4F0E5', '#C6DCD5', '#83B9B2', '#47888E', '#27536D'];

export const BLUE_RED = [
  '#104E8B', '#376B9E', '#5F89B1', '#AFC3D8', '#C5E9E3',
  '#D7E1EB', '#F2DADA', '#E5B5B5', '#D89090', '#B22222',
];

export const GROUPED = BLUE_RED;

const PALETTES: Record<string, string[]> = {
  ocean_teal: OCEAN_TEAL,
  blue_red: BLUE_RED,
  grouped: GROUPED,
  categorical: ['#154F70', '#BD6840', '#4A8E92', '#7775A7', '#9D7B36', '#5D7E68', '#A64F68', '#52719B'],
  depth: ['#F3EDC9', '#CDDDC8', '#93C4BD', '#5A9EA5', '#477992', '#455777', '#66516D'],
  thermal: ['#243C62', '#47759A', '#82AFB5', '#E8E2CD', '#DA9A70', '#A94B42'],
  chlorophyll: ['#F1EDC8', '#C8DDA7', '#83B984', '#4B8C6C', '#285C56'],
  viridis: ['#440154', '#414487', '#2A788E', '#22A884', '#7AD151', '#FDE725'],
  cividis: ['#00224E', '#24476D', '#576D72', '#8D8A66', '#C3AA4B', '#FEE838'],
  magma: ['#000004', '#2C115F', '#721F81', '#B73779', '#F1605D', '#FEB078', '#FCFDBF'],
  plasma: ['#0D0887', '#6A00A8', '#B12A90', '#E16462', '#FCA636', '#F0F921'],
  blues: ['#F7FBFF', '#DEEBF7', '#9ECAE1', '#4292C6', '#2171B5', '#08306B'],
};

const ALIASES: Record<string, string> = {
  default: 'ocean_teal',
  sequential: 'ocean_teal',
  haline: 'ocean_teal',
  diverging: 'blue_red',
  balance: 'blue_red',
  rdbu_r: 'blue_red',
  'ocean-teal': 'ocean_teal',
  'blue-red': 'blue_red',
};

function paletteName(value: string): string {
  const normalized = value.trim().toLowerCase().replaceAll(' ', '_');
  return ALIASES[normalized] ?? normalized;
}

export function resolveScientificPalette(palette: unknown, fallback = 'ocean_teal'): string[] {
  if (Array.isArray(palette)) {
    const colors = palette.filter((color): color is string => (
      typeof color === 'string' && /^#[0-9a-f]{6}$/i.test(color)
    ));
    if (colors.length >= 2 && colors.length === palette.length) return colors;
  }
  const requested = typeof palette === 'string' ? paletteName(palette) : paletteName(fallback);
  return PALETTES[requested] ?? PALETTES[paletteName(fallback)] ?? OCEAN_TEAL;
}
