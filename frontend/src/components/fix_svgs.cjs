const fs = require('fs');
let file = fs.readFileSync('c:/Users/ffd/Documents/netscope-desktop/frontend/src/components/NetworkTopologyDiagram.tsx', 'utf8');

// Fix SVG String concatenation for opacity
file = file.replace(/fill=\{color \+ "([0-9A-Fa-f]{2})"\}/g, (m, hex) => {
    let alpha = parseInt(hex, 16) / 255;
    return `fill={color} fillOpacity={${alpha.toFixed(2)}}`;
});

file = file.replace(/stroke=\{color \+ "([0-9A-Fa-f]{2})"\}/g, (m, hex) => {
    let alpha = parseInt(hex, 16) / 255;
    return `stroke={color} strokeOpacity={${alpha.toFixed(2)}}`;
});

// Replace #0d1117 background references
file = file.replace(/fill="#0d1117"/g, 'fill="rgb(var(--color-background))"');
file = file.replace(/stroke="#0d1117"/g, 'stroke="rgb(var(--color-background))"');

// Replace #3fb950 hardcodes inside SVGs
file = file.replace(/fill="#3fb950"/g, 'fill="rgb(var(--color-success))"');

fs.writeFileSync('c:/Users/ffd/Documents/netscope-desktop/frontend/src/components/NetworkTopologyDiagram.tsx', file);
console.log('Done SVG modifications for NetworkTopologyDiagram');
