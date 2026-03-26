// Cortex Memory Dashboard — Config
var CMD = window.CMD || {};
window.CMD = CMD;

CMD.CATEGORY_COLORS = {
  'bug-fix':'#ff4444','feature':'#44ff44','refactor':'#44aaff',
  'research':'#ffaa00','config':'#888','docs':'#aaddff',
  'debug':'#ff8800','architecture':'#aa44ff','deployment':'#00ddaa',
  'testing':'#ffdd00','general':'#666'
};

CMD.STAGE_COLORS = {
  labile:          '#ff4444',
  early_ltp:       '#ffaa00',
  late_ltp:        '#26de81',
  consolidated:    '#00d2ff',
  reconsolidating: '#d946ef',
};

CMD.GOLDEN = 2.399963229;
CMD.CHART_W = 264;
