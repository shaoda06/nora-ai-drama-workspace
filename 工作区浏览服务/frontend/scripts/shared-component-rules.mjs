import ts from 'typescript';
import postcss from 'postcss';

// These are implementation owners, not page exemptions. Extend with a real shared component.
const owners = {
  Dialog: 'components.tsx', TabSelect: 'components/TabSelect.tsx',
  SearchField: 'components/SearchField.tsx', Switch: 'components/Switch.tsx',
  TabNav: 'components/TabNav.tsx', UnderlineTabs: 'components/UnderlineTabs.tsx',
  Pagination: 'components/Pagination.tsx', PageHeader: 'components/PageHeader.tsx',
  FileActions: 'components/FileActions.tsx', CopyButton: 'components/CopyButton.tsx',
  Notifications: 'components/Notifications.tsx',
};
const classes = {
  'dialog-close': ['Dialog', 'style.css'],
  'tab-select': ['TabSelect', 'components/TabSelect.css', 'style.css'],
  tabs: ['TabNav', 'style.css'], 'underline-tabs': ['UnderlineTabs', 'style.css'],
  'ui-switch': ['Switch', 'components/Switch.css'], pagination: ['Pagination', 'style.css', 'components/Pagination.css'],
  'page-heading': ['PageHeader', 'style.css'], 'search-field': ['SearchField', 'style.css'],
  'floating-message': ['Notifications', 'components/Notifications.css'],
  'file-action-links': ['FileActions', 'components/FileActions.css'],
};
const componentClass = name => Object.keys(classes).find(prefix => name === prefix || name.startsWith(prefix + '-'));
const appearance = /^(?:font(?:-.+)?|color|background(?:-.+)?|padding(?:-.+)?|border(?:-.+)?|box-shadow|line-height|text-align|gap|row-gap|column-gap|display|flex-direction|flex-wrap|grid-template-.+|opacity)$/;
const literal = node => {
  if (!node) return undefined;
  if (ts.isJsxExpression(node) || ts.isParenthesizedExpression(node)) return literal(node.expression);
  return ts.isStringLiteralLike(node) ? node.text : undefined;
};

export function inspectSource(path, text) {
  const issues = [];
  const add = (rule, line, signature, message, severity = 'error') => issues.push({ rule, line, signature, message, severity });
  if (path.endsWith('.css')) {
    const root = postcss.parse(text, { from: path });
    root.walkRules(rule => {
      for (const selector of rule.selectors) {
        // :has() describes descendants, not the element receiving these declarations.
        // Track parentheses so nested conditions do not hide a component after :has().
        let depth = 0, hasDepth = 0, targetSelector = '';
        for (const token of selector.replace(/\[[^\]]*\]/g, '').match(/:has\(|[()]|[^():]+|:/g) || []) {
          if (token === ':has(') { depth++; if (!hasDepth) hasDepth = depth; }
          else if (token === '(') depth++;
          if (!hasDepth) targetSelector += token;
          if (token === ')') { if (hasDepth === depth) hasDepth = 0; depth--; }
        }
        const classNames = [...targetSelector.matchAll(/\.([\w-]+)/g)].map(match => match[1]);
        const used = classNames.map(componentClass).filter(Boolean);
        const hasDialog = /(?:^|[\s>+~,])dialog\b/.test(targetSelector);
        if (!used.length && !hasDialog) continue;
        const first = componentClass(classNames[0] || '');
        // Shared styles start at a shared root; page-qualified selectors remain overrides.
        const sharedRoot = first && used.every(name => classes[name].slice(1).includes(path)) && classes[first].slice(1).includes(path);
        const sharedDialog = path === 'style.css' && /^dialog\b/.test(selector);
        if (sharedRoot || sharedDialog) continue;
        rule.walkDecls(decl => {
          if (!appearance.test(decl.prop)) return;
          add('component-style', decl.source.start.line, `${rule.parent.type === 'atrule' ? rule.parent.toString().split('{')[0] : ''}|${selector}|${decl.prop}|${decl.value}|${decl.important}`,
            `${selector} 单独设置 ${decl.prop}；请移入公共组件规格，页面只分配布局空间。`);
        });
      }
    });
    return issues;
  }
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true,
    /\.[jt]sx$/.test(path) ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const reported = new WeakMap();
  const report = (node, component) => {
    if (path === owners[component]) return;
    const seen = reported.get(node) || new Set();
    if (seen.has(component)) return;
    seen.add(component);
    reported.set(node, seen);
    add('duplicate-ui', source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1,
      `${component}|${node.getText(source)}`, `直接实现 ${component} 的公共行为，请复用 ${component}。`);
  };
  const visit = node => {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText(source);
      const attrs = new Map(node.attributes.properties.filter(ts.isJsxAttribute).map(attr => [attr.name.getText(source), attr.initializer]));
      if (tag === 'dialog') report(node, 'Dialog');
      if (tag === 'select') report(node, 'TabSelect');
      if (tag === 'input' && literal(attrs.get('type')) === 'search') report(node, 'SearchField');
      if (tag === 'a' && attrs.has('download')) report(node, 'FileActions');
      const role = literal(attrs.get('role'));
      if (role === 'switch') report(node, 'Switch');
      if (role === 'combobox' || role === 'listbox') report(node, 'TabSelect');
      if (role === 'dialog' || role === 'alertdialog') report(node, 'Dialog');
      if (/^[a-z]/.test(tag)) {
        for (const name of (literal(attrs.get('className')) || '').split(/\s+/)) {
          const component = classes[componentClass(name)]?.[0];
          if (component && owners[component]) report(node, component);
        }
      }
    }
    if (ts.isCallExpression(node)) {
      const callee = node.expression.getText(source).replace(/\s/g, '');
      if (['navigator.clipboard.writeText', 'window.navigator.clipboard.writeText'].includes(callee)
        || (['document.execCommand', 'window.document.execCommand'].includes(callee) && literal(node.arguments[0]) === 'copy')) report(node, 'CopyButton');
      if (['URL.createObjectURL', 'window.URL.createObjectURL'].includes(callee) && path !== 'components/DownloadButton.tsx') {
        add('object-url-review', source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1, node.getText(source),
          '新增Blob URL：人工确认是否重复实现下载；图片本地预览等业务用途可保留并在W记录说明。', 'review');
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return issues;
}

// Git is the reference; no saved baseline or blanket per-page exemptions.
export function introducedIssues(previous, current) {
  const counts = new Map();
  const key = issue => `${issue.rule}|${issue.signature}`;
  for (const issue of previous) counts.set(key(issue), (counts.get(key(issue)) || 0) + 1);
  return current.filter(issue => {
    const remaining = counts.get(key(issue)) || 0;
    if (!remaining) return true;
    counts.set(key(issue), remaining - 1);
    return false;
  });
}
