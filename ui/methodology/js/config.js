// Cortex Methodology Map — Config
window.CMV = window.CMV || {};

CMV.SERVER_URL = 'http://localhost:3456/graph';

CMV.COLORS = {
  'domain':            '#00FFFF',
  'entry-point':       '#00FF88',
  'recurring-pattern': '#0080FF',
  'tool-preference':   '#FFB800',
  'blind-spot':        '#333344',
  'bridge':            '#FF00FF',
};

CMV.LABELS = {
  'domain': 'Domain Hub',
  'entry-point': 'Entry Point',
  'recurring-pattern': 'Pattern',
  'tool-preference': 'Tool Pref',
  'blind-spot': 'Blind Spot',
};

CMV.SAMPLE = {
  nodes: [
    { id: "d0", type: "domain", label: "ai architect", domain: "ai-architect", confidence: 0.76, sessionCount: 38, size: 19 },
    { id: "d1", type: "domain", label: "frontend", domain: "frontend", confidence: 0.68, sessionCount: 24, size: 15 },
    { id: "d2", type: "domain", label: "devops", domain: "devops", confidence: 0.55, sessionCount: 14, size: 12 },
    { id: "e0", type: "entry-point", label: "system design", domain: "ai-architect", confidence: 0.72, frequency: 8, size: 9 },
    { id: "e1", type: "entry-point", label: "component build", domain: "frontend", confidence: 0.61, frequency: 5, size: 7 },
    { id: "p0", type: "recurring-pattern", label: "recursive structures", domain: "ai-architect", confidence: 0.70, frequency: 8, size: 12 },
    { id: "p1", type: "recurring-pattern", label: "incremental delivery", domain: "ai-architect", confidence: 0.82, frequency: 12, size: 14 },
    { id: "p2", type: "recurring-pattern", label: "context-first reading", domain: "ai-architect", confidence: 0.91, frequency: 17, size: 16 },
    { id: "t0", type: "tool-preference", label: "Read", domain: "ai-architect", ratio: 0.92, avgPerSession: 18, size: 13 },
    { id: "t1", type: "tool-preference", label: "Grep", domain: "ai-architect", ratio: 0.85, avgPerSession: 11, size: 12 },
  ],
  edges: [
    { source: "d0", target: "e0", type: "has-entry", weight: 0.72 },
    { source: "d1", target: "e1", type: "has-entry", weight: 0.61 },
    { source: "d0", target: "p0", type: "has-pattern", weight: 0.70 },
    { source: "d0", target: "p1", type: "has-pattern", weight: 0.82 },
    { source: "d0", target: "p2", type: "has-pattern", weight: 0.91 },
    { source: "d0", target: "t0", type: "uses-tool", weight: 0.92 },
    { source: "d0", target: "t1", type: "uses-tool", weight: 0.85 },
    { source: "d0", target: "d1", type: "bridge", weight: 0.4 },
    { source: "d1", target: "d2", type: "bridge", weight: 0.3 },
  ],
  blindSpotRegions: [
    { domain: "ai-architect", type: "category", value: "testing", severity: "high", description: "0 test sessions", suggestion: "Consider TDD" },
  ]
};
