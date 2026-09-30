const PROFILE_DISPLAY_NAMES: Readonly<Record<string, string>> = {
  literature_reproduction_expert: 'Search Expert',
  ocean_process_expert: 'Ocean Expert',
  statistical_inference_expert: 'Statistic Expert',
  scientific_discussion_partner: 'Scientific discussion partner',
};

const LEGACY_DISPLAY_NAMES: Readonly<Record<string, string>> = {
  'Literature Expert': 'Search Expert',
  'Literature & Reproduction Expert': 'Search Expert',
};

export function agentDisplayName(profileId: string | null | undefined, fallback: string): string {
  return PROFILE_DISPLAY_NAMES[profileId ?? ''] ?? LEGACY_DISPLAY_NAMES[fallback] ?? fallback;
}
