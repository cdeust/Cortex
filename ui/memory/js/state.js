// Cortex Memory Dashboard — State
(function() {
  var CMD = window.CMD;

  // Data references (set during init)
  CMD.nodes = [];
  CMD.edges = [];
  CMD.nodeMap = {};
  CMD.W = window.innerWidth;
  CMD.H = window.innerHeight;

  // Three.js scene objects (set during scene init)
  CMD.scene = null;
  CMD.camera = null;
  CMD.renderer = null;
  CMD.controls = null;
  CMD.composer = null;
  CMD.neuronGroup = null;
  CMD.neuronMeshes = {};
  CMD.tractGroup = null;
  CMD.brainScale = 1;

  // Edge references
  CMD.allDrawEdges = [];
  CMD.tubeEdges = [];
  CMD.lineEdges = [];
  CMD.drawEdges = [];
  CMD.tubeCount = 0;
  CMD.eGeo = null;
  CMD.eColBuf = null;

  // Connection index maps
  CMD.tubeEdgeSet = null;
  CMD.lineEdgeSet = null;
  CMD.edgeToTubeIdx = null;
  CMD.edgeToLineIdx = null;
  CMD.nodeEdgeMap = {};

  // AP (action potential) system
  CMD.AP_POOL = [];
  CMD.AP_CURVES = [];
  CMD.AP_VALID = [];
  CMD.AP_GEO = null;
  CMD.AP_TRAIL_GEO = null;
  CMD.lastAP = 0;

  // Filter state
  CMD.activeFilter = 'all';
  CMD.searchQuery = '';
  CMD.showConvs = true;
  CMD.activeCategory = 'all';
  CMD.activeThread = '';
  CMD.activeStatus = 'all';
  CMD.layoutMode = 'cluster';

  // Highlight state
  CMD._highlightedTubes = [];
  CMD._highlightedLines = [];
  CMD._connectedNodeIds = new Set();

  // Interaction state
  CMD.hoveredNode = null;
  CMD.selectedNode = null;
  CMD.mouseScreen = { x: 0, y: 0 };
  CMD.ray = null;
  CMD.mouse = null;

  // Analytics state
  CMD.analyticsOpen = false;
  CMD.activeChartFilter = null;
  CMD._bindState = {};

  // Animation
  CMD.frame = 0;

  // Glow texture (set during brain init)
  CMD.GLOW_TEX = null;

  // Node categories
  CMD.hubNs = [];
  CMD.convNs = [];
  CMD.globalNs = [];
  CMD.planNs = [];
  CMD.pluginNs = [];
  CMD.todoNs = [];
})();
