import {renderToStaticMarkup} from 'react-dom/server';
import {describe, expect, it} from 'vitest';

import type {ParallelExperts} from '../../parallel-experts.js';
import {DesktopSettingsDialog} from './DesktopSettingsDialog.js';

function settings(parallelExperts: ParallelExperts): string {
  return renderToStaticMarkup(<DesktopSettingsDialog
    open
    status="Ready"
    projectName="Gulf"
    runtime={null}
    modelProvider={null}
    modelProviderSaving={false}
    displayDensity="comfortable"
    onDisplayDensity={() => {}}
    appearanceTheme="system"
    onAppearanceTheme={() => {}}
    parallelExperts={parallelExperts}
    onParallelExperts={() => {}}
    onConfigureModelProvider={() => {}}
    update={{configured: false, state: 'idle'} as never}
    onCheckForUpdate={() => {}}
    onInstallUpdate={() => {}}
    onClose={() => {}}
  />);
}

describe('DesktopSettingsDialog', () => {
  it('lets the researcher choose how many data Experts work at once', () => {
    const markup = settings(3);
    expect(markup).toContain('aria-label="Parallel data Experts"');
    const group = markup.slice(markup.indexOf('aria-label="Parallel data Experts"'));
    const buttons = [...group.slice(0, group.indexOf('</div>')).matchAll(/<button class="([^"]*)" aria-pressed="(true|false)">(\d)<\/button>/g)];
    expect(buttons.map((match) => match[3])).toEqual(['1', '2', '3', '4']);
    expect(buttons.filter((match) => match[2] === 'true').map((match) => match[3])).toEqual(['3']);
    expect(buttons.filter((match) => match[1] === 'active').map((match) => match[3])).toEqual(['3']);
    expect(markup).toContain('The Search Expert has its own slot');
  });
});
