const fs = require('fs');

const mappings = {
  '#58a6ff': 'rgb(var(--color-accent))',
  '#3fb950': 'rgb(var(--color-success))',
  '#f0883e': 'rgb(var(--color-tool))',
  '#d29922': 'rgb(var(--color-warning))',
  '#bc8cff': 'rgb(var(--color-purple))',
  '#79c0ff': 'rgb(var(--color-accent-muted))',
  '#56d364': 'rgb(var(--color-success-emphasis))',
  '#ff7b72': 'rgb(var(--color-danger))',
  '#ffa657': 'rgb(var(--color-severe))',
  '#484f58': 'rgb(var(--color-muted-dim))',
  '#f85149': 'rgb(var(--color-danger))',
  '#2d1b1b': 'rgb(var(--color-danger-subtle))',
  '#161b22': 'rgb(var(--color-surface))',
  '#0d1117': 'rgb(var(--color-background))',
  '#8b949e': 'rgb(var(--color-muted))',
  '#c9d1d9': 'rgb(var(--color-foreground))',
  '#30363d': 'rgb(var(--color-border))',
  '#21262d': 'rgb(var(--color-surface-hover))'
};

const files = [
  'c:/Users/ffd/Documents/netscope-desktop/frontend/src/components/TrafficMap.tsx',
  'c:/Users/ffd/Documents/netscope-desktop/frontend/src/components/NetworkTopologyDiagram.tsx',
  'c:/Users/ffd/Documents/netscope-desktop/frontend/src/components/SchedulerPanel.tsx'
];

files.forEach(file => {
  if (!fs.existsSync(file)) return;
  let content = fs.readFileSync(file, 'utf8');
  for (const [hex, cssColor] of Object.entries(mappings)) {
    // Replace hex (case insensitive)
    const regex = new RegExp(hex, 'gi');
    content = content.replace(regex, cssColor);
  }
  fs.writeFileSync(file, content);
});

console.log('Hex replacement done.');
