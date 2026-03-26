// Cortex Memory Dashboard — Styling
(function() {
  var CMD = window.CMD;

  CMD.stageColor = function(stage) {
    return new THREE.Color(CMD.STAGE_COLORS[stage] || CMD.STAGE_COLORS.labile);
  };

  CMD.nodeColor = function(n) {
    // Cortex memory types — blend store_type color with consolidation stage
    if (n.store_type === 'episodic' || n.store_type === 'semantic') {
      var base = n.store_type === 'episodic'
        ? new THREE.Color('#26de81')
        : new THREE.Color('#d946ef');
      if (n.consolidation_stage && CMD.STAGE_COLORS[n.consolidation_stage]) {
        var sc = CMD.stageColor(n.consolidation_stage);
        base.lerp(sc, 0.3);
      }
      return base;
    }
    // Entity nodes
    if (n.id && n.id.startsWith('e_')) return new THREE.Color('#00d2ff');
    // Fallback to original brain.html types
    if (n.nodeType === 'global-instruction') return new THREE.Color('#ffffff');
    if (n.nodeType === 'settings')           return new THREE.Color('#d0d0d0');
    if (n.nodeType === 'project-hub')        return new THREE.Color('#f5a623');
    if (n.nodeType === 'memory-index')       return new THREE.Color('#00c8ff');
    if (n.nodeType === 'project-file')       return new THREE.Color('#80cbc4');
    if (n.nodeType === 'plan')               return new THREE.Color('#ab47bc');
    if (n.nodeType === 'mcp-tool')           return new THREE.Color('#69f0ae');
    if (n.nodeType === 'plugin')             return new THREE.Color('#7c4dff');
    if (n.nodeType === 'todo')               return new THREE.Color('#ffca28');
    if (n.nodeType === 'conversation')       return new THREE.Color('#ef9a9a');
    if (n.nodeType === 'memory') {
      if (n.type === 'user')      return new THREE.Color('#26de81');
      if (n.type === 'feedback')  return new THREE.Color('#ff7043');
      if (n.type === 'project')   return new THREE.Color('#ffd740');
      if (n.type === 'reference') return new THREE.Color('#f06292');
      return new THREE.Color('#4fc3f7');
    }
    return new THREE.Color('#888888');
  };

  CMD.neuronR = function(n) {
    // Cortex memory types
    if (n.id && n.id.startsWith('e_')) return 4.5 + Math.min(n.connections || 0, 15) * 0.15;
    if (n.store_type === 'episodic')   return 2.5 + (n.importance || 0.5) * 1.5;
    if (n.store_type === 'semantic')   return 2.8 + (n.importance || 0.5) * 1.5;
    // Fallback to original brain.html sizing
    if (n.nodeType === 'global-instruction') return 8;
    if (n.nodeType === 'settings')           return 6.5;
    if (n.nodeType === 'project-hub')        return 5.5 + Math.min(n.connections || 0, 12) * 0.12;
    if (n.nodeType === 'memory-index')       return 4;
    if (n.nodeType === 'memory')             return 3;
    if (n.nodeType === 'plan')               return 2.6;
    if (n.nodeType === 'project-file')       return 2.4;
    if (n.nodeType === 'mcp-tool')           return 2.1;
    if (n.nodeType === 'plugin')             return 2.5;
    if (n.nodeType === 'todo')               return 1.9;
    if (n.nodeType === 'conversation')       return 2.5;
    return 1.8;
  };
})();
