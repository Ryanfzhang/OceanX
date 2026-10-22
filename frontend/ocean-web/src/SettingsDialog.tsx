import {Cog, X} from 'lucide-react';
import type {ModelProviderStatus} from '../../ocean-desktop/src/shared/bridge.js';
import {useUiLanguage} from '../../ocean-desktop/src/renderer/i18n.js';
import {ModalDialog} from '../../ocean-desktop/src/renderer/components/dialogs/ModalDialog.js';
import {PARALLEL_EXPERTS_CHOICES, type ParallelExperts} from '../../ocean-desktop/src/renderer/parallel-experts.js';
import type {AppearanceTheme, DisplayDensity} from '../../ocean-desktop/src/renderer/types.js';

type Props = {
  open: boolean; status: string; modelProvider: ModelProviderStatus | null;
  displayDensity: DisplayDensity; onDisplayDensity: (value: DisplayDensity) => void;
  appearanceTheme: AppearanceTheme; onAppearanceTheme: (value: AppearanceTheme) => void;
  parallelExperts: ParallelExperts; onParallelExperts: (value: ParallelExperts) => void;
  onClose: () => void;
};
export function DesktopSettingsDialog(props: Props): React.JSX.Element | null {
  const {language, setLanguage, text} = useUiLanguage();
  if (!props.open) return null;
  return <ModalDialog ariaLabel={text('Settings', '设置')} className="desktop-settings-dialog" onClose={props.onClose}>
    <header><div><Cog size={17} /><strong>{text('Settings', '设置')}</strong></div><button onClick={props.onClose} aria-label={text('Close settings', '关闭设置')}><X size={15} /></button></header>
    <section className="settings-section"><h2>{text('Connection', '连接')}</h2><p>{props.status}</p><dl className="settings-facts">
      {(['coordinator', 'expert'] as const).map(role => <div key={role}><dt>{role === 'coordinator' ? text('Coordinator', '协调者') : text('Experts', '专家')}</dt><dd>{props.modelProvider?.[role].model ?? '—'}</dd></div>)}
    </dl><p className="settings-section-summary">{text('Model APIs are configured on the server.', '模型接口在服务器上配置。')}</p></section>
    <section className="settings-section"><h2>{text('Research', '研究')}</h2><div className="settings-appearance-control"><span>{text('Parallel data Experts', '同时工作的数据专家')}</span><div className="settings-density" role="group" aria-label="Parallel data Experts">{PARALLEL_EXPERTS_CHOICES.map(count => <button key={count} className={props.parallelExperts === count ? 'active' : ''} onClick={() => props.onParallelExperts(count)}>{count}</button>)}</div></div></section>
    <section className="settings-section"><h2>{text('Appearance and language', '外观与语言')}</h2>
      <div className="settings-appearance-control"><span>{text('Interface language', '界面语言')}</span><div className="settings-density" role="group" aria-label="Interface language">{(['en','zh'] as const).map(value => <button key={value} className={language === value ? 'active' : ''} onClick={() => setLanguage(value)}>{value === 'en' ? 'English' : '中文'}</button>)}</div></div>
      <div className="settings-appearance-control"><span>{text('Color theme', '颜色主题')}</span><div className="settings-density" role="group" aria-label="Color theme">{(['system','light','dark'] as const).map((value, i) => <button key={value} className={props.appearanceTheme === value ? 'active' : ''} onClick={() => props.onAppearanceTheme(value)}>{[text('System','跟随系统'),text('Light','浅色'),text('Dark','深色')][i]}</button>)}</div></div>
      <div className="settings-appearance-control"><span>{text('Interface density', '界面密度')}</span><div className="settings-density" role="group" aria-label="Interface density">{(['comfortable','compact'] as const).map(value => <button key={value} className={props.displayDensity === value ? 'active' : ''} onClick={() => props.onDisplayDensity(value)}>{value === 'comfortable' ? text('Comfortable','舒适') : text('Compact','紧凑')}</button>)}</div></div>
    </section>
  </ModalDialog>;
}
