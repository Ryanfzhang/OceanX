import Markdown, {type Components} from 'react-markdown';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';

import type {ArtifactRef} from './types.js';

export type MarkdownArtifactLink = {
  ref: ArtifactRef;
  label: string;
  onOpen: () => void;
};

export type MarkdownResultLink = {
  keys: string[];
  keyLabels?: Record<string, string>;
  label: string;
  summary?: string;
  kind: 'interactive_view' | 'report' | 'file' | 'table';
  features?: Array<{id: string; label: string}>;
  onOpen: (featureId?: string) => void;
};

const RESULT_MARKER_RE = /\[\[(?:result|output):([^\]|\r\n]+)(?:\|([^\]\r\n]+))?\]\]/g;
const RESULT_SHORTHAND_RE = /\[([A-Za-z][A-Za-z0-9_.\/-]{0,159})\](?!\()/g;
const RESULT_IMAGE_RE = /!\[([^\]\r\n]*)\]\(([^)\r\n]+)\)/g;
const LABELED_RESULT_ITEM_RE = /^\s*\[\[(?:result|output):([^\]\r\n]+)\]\]\s*[（(]([^）)\r\n]+)[）)]\s*[。.]*\s*$/;

function resultLookup(items: MarkdownResultLink[]): Map<string, MarkdownResultLink | null> {
  const lookup = new Map<string, MarkdownResultLink | null>();
  for (const item of items) for (const key of item.keys) {
    lookup.set(key, lookup.has(key) && lookup.get(key) !== item ? null : item);
  }
  return lookup;
}

/** Collapse only adjacent standalone aliases for the same result/object, never narrative or code. */
export function deduplicateResultLinks(content: string, items: MarkdownResultLink[]): string {
  const lookup = resultLookup(items);
  return content.split(/(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/).map((part, index) => {
    if (index % 2) return part;
    let last: string | undefined;
    return part.split(/(?<=\n)/).filter(line => {
      const marker = line.match(/^\s*(?:[-*]\s+)?\[\[(?:result|output):([^|\]\r\n]+)(?:\|[^\]\r\n]+)?\]\]\s*$/);
      if (!marker) {if (line.trim()) last = undefined; return true;}
      const [base, ...fragment] = marker[1]!.trim().split('#');
      const result = lookup.get(base!);
      const key = result ? `${items.indexOf(result)}#${fragment.join('#')}` : marker[1];
      if (key === last) return false;
      last = key;
      return true;
    }).join('');
  }).join('');
}

/** Keep previously saved, dot-separated result references readable in the compact list layout. */
export function normalizeLabeledResultLists(content: string): string {
  return content.split(/\r?\n/).map((line) => {
    const parts = line.split(/\s*·\s*/);
    if (parts.length < 2) return line;
    const items = parts.map((part) => part.match(LABELED_RESULT_ITEM_RE));
    if (items.some((item) => item === null)) return line;
    return items.map((item) => {
      const key = item?.[1].trim() ?? '';
      const label = item?.[2].trim() ?? '';
      return `- [[result:${key}|${label}]]`;
    }).join('\n');
  }).join('\n');
}

export function referencedResultKeys(content: string): Set<string> {
  return new Set([
    ...Array.from(content.matchAll(RESULT_MARKER_RE), (match) => match[1].trim().split('#')[0]!),
    ...Array.from(content.matchAll(RESULT_SHORTHAND_RE), (match) => match[1].trim()),
  ]);
}

export function safeExternalHref(value: string | undefined): string | null {
  if (!value) {
    return null;
  }

  try {
    const url = new URL(value);
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : null;
  } catch {
    return null;
  }
}

const baseComponents: Components = {
  a: ({href, children}) => {
    const safeHref = safeExternalHref(href);
    return safeHref ? (
      <a href={safeHref} target="_blank" rel="noreferrer noopener">
        {children}
      </a>
    ) : (
      <span>{children}</span>
    );
  },
  code: ({className, children}) => <code className={className}>{children}</code>,
  img: ({alt}) => <span className="markdown-image-placeholder">[Image: {alt || 'unavailable'}]</span>,
  pre: ({children}) => <pre className="markdown-code-block">{children}</pre>,
  table: ({children}) => (
    <div className="markdown-table">
      <table>{children}</table>
    </div>
  ),
};

/** Render compact trusted prose without allowing block layout or nested interactive links. */
export function InlineMarkdown({content}: {content: string}) {
  return <span className="inline-markdown">
    <Markdown
      allowedElements={['strong', 'em', 'del', 'code']}
      components={{code: ({children}) => <code>{children}</code>}}
      remarkPlugins={[remarkGfm]}
      skipHtml
      unwrapDisallowed
    >
      {content.replace(/\s+/g, ' ').trim()}
    </Markdown>
  </span>;
}

const compactLogComponents: Components = {
  ...baseComponents,
  p: ({children}) => <>{children}{' '}</>,
  h1: ({children}) => <><strong>{children}</strong>{' — '}</>,
  h2: ({children}) => <><strong>{children}</strong>{' — '}</>,
  h3: ({children}) => <><strong>{children}</strong>{' — '}</>,
  h4: ({children}) => <><strong>{children}</strong>{' — '}</>,
  ul: ({children}) => <>{children}</>,
  ol: ({children}) => <>{children}</>,
  li: ({children}) => <span className="compact-log-list-item">{children}</span>,
  blockquote: ({children}) => <>{children}{' '}</>,
  pre: ({children}) => <span className="compact-log-code">{children}</span>,
  table: ({children}) => <span className="compact-log-table">{children}</span>,
  thead: ({children}) => <>{children}</>,
  tbody: ({children}) => <>{children}</>,
  tr: ({children}) => <span className="compact-log-table-row">{children}</span>,
  th: ({children}) => <span className="compact-log-table-cell">{children}</span>,
  td: ({children}) => <span className="compact-log-table-cell">{children}</span>,
};

/** Preserve useful Markdown semantics while keeping every research-log update in one text flow. */
export function CompactLogMarkdown({content}: {content: string}) {
  return <span className="compact-log-markdown">
    <Markdown
      components={compactLogComponents}
      rehypePlugins={[rehypeKatex]}
      remarkPlugins={[remarkGfm, remarkMath]}
      skipHtml
    >
      {content}
    </Markdown>
  </span>;
}

function artifactKeys(ref: ArtifactRef): string[] {
  return [
    `${ref.artifact_id}@v${ref.version}`,
    `${ref.artifact_id}@v${String(ref.version).padStart(4, '0')}`,
  ];
}

function plainResultText(value: string): string {
  return value.replace(/[*_~`]/g, '').replace(/\s+/g, ' ').trim();
}

export function MessageMarkdown({
  content,
  artifactLinks = [],
  resultLinks = [],
}: {
  content: string;
  artifactLinks?: MarkdownArtifactLink[];
  resultLinks?: MarkdownResultLink[];
}) {
  const links = new Map(artifactLinks.flatMap((item) => artifactKeys(item.ref).map((key) => [key, item] as const)));
  const results = resultLookup(resultLinks);
  const markerTokens = new Map<string, {key: string; label?: string}>();
  let markerIndex = 0;
  const renderedContent = deduplicateResultLinks(normalizeLabeledResultLists(content), resultLinks)
    .split(/(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)/).map((part, index) => {
      if (index % 2) return part;
      const linkedImages = part.replace(RESULT_IMAGE_RE, (match, alt: string, source: string) => {
        const fileName = source.trim().split(/[\\/]/).at(-1) ?? '';
        const key = fileName.replace(/\.preview\.[A-Za-z0-9]+$/i, '').replace(/\.[A-Za-z0-9]+$/i, '');
        if (!results.get(key)) return match;
        const token = `ocean-result-${markerIndex}`;
        markerIndex += 1;
        markerTokens.set(token, {key, label: alt.trim() || undefined});
        return `\`${token}\``;
      });
      const explicit = linkedImages.replace(RESULT_MARKER_RE, (_match, key: string, label?: string) => {
        const normalizedKey = key.trim();
        const baseKey = normalizedKey.split('#')[0]!;
        const token = `ocean-result-${markerIndex}`;
        markerIndex += 1;
        markerTokens.set(token, {
          key: normalizedKey,
          label: label?.trim() || results.get(baseKey)?.keyLabels?.[baseKey],
        });
        return `\`${token}\``;
      });
      return explicit.replace(RESULT_SHORTHAND_RE, (match, key: string) => {
        const result = results.get(key);
        if (!result) return match;
        const token = `ocean-result-${markerIndex}`;
        markerIndex += 1;
        markerTokens.set(token, {key, label: result.keyLabels?.[key] ?? key});
        return `\`${token}\``;
      });
    }).join('');
  const components: Components = {
    ...baseComponents,
    code: ({className, children}) => {
      const value = String(children).trim();
      const marker = markerTokens.get(value);
      const [baseKey, ...fragment] = marker?.key.split('#') ?? [];
      const featureId = fragment.length ? fragment.join('#') : undefined;
      const result = baseKey ? results.get(baseKey) : undefined;
      const feature = featureId ? result?.features?.find(item => item.id === featureId) : undefined;
      if (featureId !== undefined && !feature) {
        return <span className="markdown-result-unavailable" role="status" title={`Unknown result object: ${featureId}`}>Result object unavailable: {featureId || '(empty)'}</span>;
      }
      if (result) {
        const accessibleLabel = plainResultText(feature?.label ?? result.label);
        return (
          <button
            aria-label={`Open ${accessibleLabel}`}
            className="markdown-result-link"
            type="button"
            onClick={() => result.onOpen(featureId)}
            title={[baseKey, plainResultText(result.label), result.summary ? plainResultText(result.summary) : undefined].filter(Boolean).join(' — ')}
          >
            {feature?.label ?? marker?.label ?? result.label}
          </button>
        );
      }
      if (marker) {
        return <span className="markdown-result-unavailable" title="This supporting result is not available in the current task snapshot">{marker.label ?? 'Supporting result unavailable'}</span>;
      }
      const link = links.get(value);
      return link ? <button className="markdown-artifact-link" type="button" onClick={link.onOpen} title={`Open ${link.label} in the right workbench`}>{link.label}</button> : <code className={className}>{children}</code>;
    },
  };
  return (
    <div className="message-markdown">
      <Markdown
        components={components}
        rehypePlugins={[rehypeKatex]}
        remarkPlugins={[remarkGfm, remarkMath]}
        skipHtml
      >
        {renderedContent}
      </Markdown>
    </div>
  );
}
