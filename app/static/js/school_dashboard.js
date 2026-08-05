/* ============================================================
   school_dashboard.js — TechCare-cloned school dashboard
   ============================================================ */
(function () {
  'use strict';

  /* ---------- helpers ---------- */
  var $ = function (s, p) { return (p || document).querySelector(s); };
  var $$ = function (s, p) { return Array.from((p || document).querySelectorAll(s)); };
  var escHtml = function (s) {
    var d = document.createElement('div');
    d.appendChild(document.createTextNode(s));
    return d.innerHTML;
  };

  /* ---------- data node ---------- */
  var node = $('#schoolDashboardData');
  if (!node) return;

  var DATA = {
    stage:            JSON.parse(node.dataset.stage || '{}'),
    coverage:         JSON.parse(node.dataset.coverage || '{}'),
    monthly:          JSON.parse(node.dataset.monthly || '{}'),
    totalStudents:    parseInt(node.dataset.totalStudents) || 0,
    totalResults:     parseInt(node.dataset.totalResults) || 0,
    atRisk:           parseInt(node.dataset.atRisk) || 0,
    schoolId:         node.dataset.schoolId,
    schoolName:       node.dataset.schoolName,
    period:           node.dataset.period || 'all',
    uploadEnabled:    node.dataset.uploadEnabled === 'true',
    paystackKey:      node.dataset.paystackKey || '',
    email:            node.dataset.email || '',
    amount:           parseInt(node.dataset.amount) || 0,
    currency:         node.dataset.currency || 'GHS',
    testMode:         node.dataset.testMode === 'true',
    verifyUrl:        node.dataset.verifyUrl,
    studentsUrl:      node.dataset.studentsUrl,
    classesUrl:       node.dataset.classesUrl,
    claimCodesUrl:    node.dataset.claimCodesUrl
  };

  function getCSRF() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  /* ---------- DOM refs ---------- */
  var sidebar          = $('#sdSidebar');
  var studentList      = $('#sdStudentList');
  var emptySidebar     = $('#sdEmptySidebar');
  var sidebarCount     = $('#sdSidebarCount');
  var sidebarFilterWrap = $('#sdSidebarFilter');
  var sidebarFilter     = $('#sdClassFilter');
  var chartClassFilter  = $('#sdChartClassFilter');
  var mainContent      = $('#sdMainContent');
  var graphToggle      = $('#sdGraphToggle');
  var graphBtn         = $('#sdGraphBtn');
  var graphDropdown    = $('#sdGraphDropdown');
  var periodBtn        = $('#sdPeriodBtn');
  var periodDropdown   = $('#sdPeriodDropdown');
  var chartTitle       = $('#sdChartTitle');
  var chartEmpty       = $('#sdChartEmpty');
  var profileDropdown  = $('#sdProfileDropdown');

  /* ---------- chart state ---------- */
  var donutChart   = null;
  var barChart     = null;
  var lineChart    = null;
  var progressChart = null;
  var resultsDonutChart = null;
  var resultsBarChart = null;
  var resultsLineChart = null;
  var resultsChartType = 'line';
  var activeGraph  = 'line';
  var currentStudentData = null;
  var currentClassFilter = '';
  var lastStudentTotal = 0;
  var prevClassFilter = '';
  var cachedClasses = [];
  var SEARCH_OPTION = '__search';
  var resultsTab = 'results';
  var resultsClassFilter = '';
  var riskClassFilter = '';

  /* save the default mainContent HTML for restore */
  var savedMainHTML = mainContent ? mainContent.innerHTML : '';

  /* ---------- chart colours (single source of truth: CSS variables) ---------- */
  function cssVar(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name);
    return (v && v.trim()) ? v.trim() : fallback;
  }

  var COLORS = {
    green:  cssVar('--sd-green', '#4a7c59'),
    gold:   cssVar('--sd-gold', '#c9921a'),
    teal:   '#2a7a7a',
    red:    cssVar('--sd-stage-clinical', '#d64541'),
    muted:  cssVar('--sd-stage-unknown', '#98a1a8'),
    bg:     cssVar('--sd-bg', '#f6f6f6'),
    border: cssVar('--sd-border', '#ededed'),
    text:   cssVar('--sd-gray', '#707070'),
    white:  '#ffffff'
  };

  /* spline-area fill: strongest right under the line, fading to transparent at the bottom (CanvasJS-style shaded volume) */
  function areaFill(color) {
    return function (context) {
      var chartArea = context.chart.chartArea;
      if (!chartArea) return color + '20';
      var g = context.chart.ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
      g.addColorStop(0, color + '52');
      g.addColorStop(0.55, color + '1a');
      g.addColorStop(1, color + '00');
      return g;
    };
  }

  var STAGE_COLOURS = {
    'Normal':   cssVar('--sd-stage-normal', '#2f9e5f'),
    'Mild':     cssVar('--sd-stage-mild', '#d9a11b'),
    'Elevated': cssVar('--sd-stage-elevated', '#e07b2a'),
    'Clinical': cssVar('--sd-stage-clinical', '#d64541'),
    'At Risk':  cssVar('--sd-stage-clinical', '#d64541'),
    'Unknown':  COLORS.muted
  };

  function stageColour(label) {
    var key = label.replace(/\s*Stage$/i, '');
    return STAGE_COLOURS[key] || COLORS.muted;
  }

  /* --- stage distribution (shared between overview + results tabs) --- */
  var STAGE_ORDER = ['Normal', 'Mild', 'Elevated', 'Clinical'];

  function stageRank(label) {
    var idx = STAGE_ORDER.indexOf((label || '').replace(/\s*Stage$/i, ''));
    return idx === -1 ? STAGE_ORDER.length : idx;
  }

  function padStageItems(items) {
    var seen = {};
    items.forEach(function (d) { seen[stageRank(d.label)] = true; });
    STAGE_ORDER.forEach(function (key, idx) {
      if (!seen[idx]) items.push({ label: key + ' Stage', value: 0 });
    });
    return items.sort(function (a, b) { return stageRank(a.label) - stageRank(b.label); });
  }

  function buildStageItems(data) {
    var arr = Array.isArray(data)
      ? data
      : Object.keys(data).map(function (l) { return { label: l, value: data[l] }; });
    return padStageItems(arr.map(function (d) {
      return { label: d.label, value: parseInt(d.value, 10) || 0 };
    }));
  }

  function renderStageKey(keyEl, items) {
    var total = items.reduce(function (a, b) { return a + b.value; }, 0);
    keyEl.innerHTML = items.map(function (d) {
      var pct = total ? Math.round(d.value / total * 100) : 0;
      return '<li class="sd-stage-key__item">' +
        '<span class="sd-stage-key__chip" style="background:' + stageColour(d.label) + ';"></span>' +
        '<span class="sd-stage-key__label">' + escHtml(d.label.replace(/\s*Stage$/i, '')) + '</span>' +
        '<span class="sd-stage-key__count">' + d.value + '</span>' +
        '<span class="sd-stage-key__pct">' + pct + '%</span>' +
        '</li>';
    }).join('');
  }

  function mountStageDoughnut(canvas, items, totalEl) {
    var labels = items.map(function (d) { return d.label; });
    var values = items.map(function (d) { return d.value; });
    var colours = labels.map(stageColour);

    var chart = new Chart(canvas.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{ data: values, backgroundColor: colours, borderWidth: 0, hoverBorderWidth: 0 }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '66%',
        plugins: {
          legend: { display: false },
          tooltip: {
            displayColors: false,
            callbacks: {
              label: function (ctx) {
                var total = ctx.dataset.data.reduce(function (a, b) { return a + b; }, 0);
                var pct = total ? Math.round(ctx.raw / total * 100) : 0;
                return ctx.label.replace(/\s*Stage$/i, '') + ': ' + ctx.raw + ' (' + pct + '%)';
              }
            }
          }
        }
      }
    });

    if (totalEl) totalEl.textContent = values.reduce(function (a, b) { return a + b; }, 0);
    return chart;
  }

  /* ==========================================================
     MONTHLY DICT → CHART HELPER
     Converts {"2025-01": 5, "2025-02": 3} to
     [{key:"2025-01", label:"Jan 2025", value:5}, ...]
     ========================================================== */
  var MONTH_NAMES = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  function monthlyDictToArray(dict) {
    if (!dict || typeof dict !== 'object' || Array.isArray(dict)) {
      /* already an array or empty — handle legacy array format */
      if (Array.isArray(dict) && dict.length > 0 && dict[0].label !== undefined) {
        return dict.map(function (d) { return { key: d.month || d.label, label: d.label, value: d.average }; });
      }
      return [];
    }
    return Object.keys(dict).sort().map(function (k) {
      var parts = k.split('-');
      var m = parseInt(parts[1], 10) - 1;
      var label = (MONTH_NAMES[m] || k) + ' ' + parts[0];
      return { key: k, label: label, value: dict[k] };
    });
  }

  /* ==========================================================
     CHART INIT FUNCTIONS (all lazy)
     ========================================================== */

  function setChartEmpty(empty) {
    if (chartEmpty) chartEmpty.classList.toggle('visible', empty);
  }

  /* --- donut view (stage distribution — pie + key) --- */
  function initDonutChart() {
    var canvas = $('#dashDonut');
    var keyEl = $('#sdDashStageKey');
    var totalEl = $('#dashDonutTotal');
    if (!canvas || !keyEl) return;
    if (donutChart) { donutChart.destroy(); donutChart = null; }

    var items = buildStageItems(DATA.stage);
    if (!items.length) {
      setChartEmpty(true);
      keyEl.innerHTML = '';
      if (totalEl) totalEl.textContent = '0';
      return;
    }
    setChartEmpty(false);
    donutChart = mountStageDoughnut(canvas, items, totalEl);
    renderStageKey(keyEl, items);
  }

  /* --- bar (coverage — dashboard coverage_counts is {test_type: count}) --- */
  function initBarChart() {
    var canvas = $('#dashBar');
    if (!canvas) return;
    if (barChart) { barChart.destroy(); barChart = null; }

    var labels = Object.keys(DATA.coverage);
    var values = Object.values(DATA.coverage);

    if (labels.length === 0) {
      setChartEmpty(true);
      return;
    }
    setChartEmpty(false);

    barChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          backgroundColor: COLORS.green,
          borderRadius: 6,
          maxBarThickness: 36
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            beginAtZero: true,
            grid: { color: COLORS.border },
            ticks: { font: { family: 'Manrope' } }
          },
          y: {
            grid: { display: false },
            ticks: { font: { family: 'Manrope', weight: '600' } }
          }
        }
      }
    });
  }

  /* --- line (monthly trends — DATA.monthly is dict[str, int]) --- */
  function initLineChart() {
    var canvas = $('#dashLine');
    if (!canvas) return;
    if (lineChart) { lineChart.destroy(); lineChart = null; }

    var arr = monthlyDictToArray(DATA.monthly);

    if (arr.length === 0) {
      setChartEmpty(true);
      updateLineLegend([]);
      return;
    }
    setChartEmpty(false);

    var labels = arr.map(function (d) { return d.label; });
    var values = arr.map(function (d) { return d.value; });

    lineChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          borderColor: COLORS.green,
          backgroundColor: areaFill(COLORS.green),
          fill: true,
          tension: 0.4,
          borderWidth: 2,
          borderCapStyle: 'round',
          pointBackgroundColor: COLORS.green,
          pointBorderColor: '#ffffff',
          pointRadius: 4,
          pointHoverRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(0,0,0,0.06)', drawTicks: false },
            border: { display: false },
            ticks: {
              font: { family: 'Manrope', size: 11 },
              color: COLORS.text
            }
          },
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: { font: { family: 'Manrope', size: 11 }, color: COLORS.text }
          }
        }
      }
    });

    updateLineLegend(values);
  }

  function updateLineLegend(values) {
    var testsEl = $('#sdLineAvg');
    var monthsEl = $('#sdLineMonths');
    if (testsEl) {
      if (!values || values.length === 0) {
        testsEl.textContent = '—';
      } else {
        /* monthly values are test counts (not percentages) — show the latest month */
        testsEl.textContent = String(values[values.length - 1]);
      }
    }
    if (monthsEl) monthsEl.textContent = values ? values.length : 0;
  }

  /* --- compute status summary from monthly average values (higher % = better) --- */
  function computeStudentStatus(values) {
    if (!values || values.length === 0) {
      return { label: 'No Data', cls: '', trend: '', delta: 0, avg: 0, latest: 0 };
    }
    var avg = Math.round(values.reduce(function (a, b) { return a + b; }, 0) / values.length);
    var latest = values[values.length - 1];
    var delta = latest - avg;

    /* status from average */
    var label, cls;
    if (avg >= 80)      { label = 'Excellent'; cls = 'sd-badge--normal'; }
    else if (avg >= 60) { label = 'Good';      cls = 'sd-badge--normal'; }
    else if (avg >= 40) { label = 'Moderate';   cls = 'sd-badge--mild'; }
    else if (avg >= 20) { label = 'Needs Attention'; cls = 'sd-badge--elevated'; }
    else                { label = 'Critical';   cls = 'sd-badge--clinical'; }

    /* trend from latest vs average */
    var trend, arrow;
    if (delta > 3)       { trend = 'Improving'; arrow = '&#9650;'; }
    else if (delta < -3) { trend = 'Worsening'; arrow = '&#9660;'; }
    else                 { trend = 'Stable';    arrow = '&#8212;'; }

    return { label: label, cls: cls, trend: trend, arrow: arrow, delta: Math.abs(delta), avg: avg, latest: latest };
  }

  /* --- student progress chart (monthlyData from student detail IS [{month,label,average}]) --- */
  function initProgressChart(monthlyData) {
    var canvas = $('#sdProgressCanvas');
    if (!canvas) return;
    if (progressChart) { progressChart.destroy(); progressChart = null; }

    var emptyEl = $('#sdStudentChartEmpty');

    if (!monthlyData || monthlyData.length === 0) {
      if (emptyEl) emptyEl.classList.add('visible');
      return;
    }
    if (emptyEl) emptyEl.classList.remove('visible');

    var labels = monthlyData.map(function (d) { return d.label; });
    var values = monthlyData.map(function (d) { return d.average; });
    /* colour segments: green where avg >= 70, red where avg < 70 */
    var segmentColours = values.map(function (v) { return v >= 70 ? COLORS.green : COLORS.red; });

    progressChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          borderColor: COLORS.green,
          backgroundColor: areaFill(COLORS.green),
          fill: true,
          tension: 0.4,
          borderWidth: 2,
          borderCapStyle: 'round',
          pointBackgroundColor: segmentColours,
          pointBorderColor: '#ffffff',
          pointRadius: 4,
          pointHoverRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        aspectRatio: 2.2,
        plugins: { legend: { display: false } },
        scales: {
          y: {
            beginAtZero: true,
            max: 100,
            grid: { color: 'rgba(0,0,0,0.06)', drawTicks: false },
            border: { display: false },
            ticks: {
              font: { family: 'Manrope', size: 12 },
              color: COLORS.text,
              callback: function (v) { return v + '%'; }
            }
          },
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: { font: { family: 'Manrope', size: 12 }, color: COLORS.text }
          }
        }
      }
    });

    /* populate side legend */
    var status = computeStudentStatus(values);
    var statusEl = $('#sdStudentStatus');
    var latestEl = $('#sdStudentLatest');
    var avgEl = $('#sdStudentAvg');
    var trendEl = $('#sdStudentTrend');
    if (statusEl) statusEl.innerHTML = '<span class="sd-badge ' + status.cls + '">' + status.label + '</span>';
    if (latestEl) latestEl.textContent = status.latest + '%';
    if (avgEl) avgEl.textContent = status.avg + '%';
    if (trendEl) trendEl.innerHTML = '<span class="sd-legend-summary__arrow">' + status.arrow + '</span> ' + status.trend + (status.delta ? ' (' + status.delta.toFixed(2) + '%)' : '');
  }

  /* ==========================================================
     GRAPH TYPE TOGGLE
     ========================================================== */
  var GRAPH_LABELS = { donut: 'Stage Distribution', bar: 'Assessment Coverage', line: 'Monthly Trends' };

  function switchGraph(type) {
    if (type === activeGraph) return;
    activeGraph = type;

    /* update dropdown button label */
    if (graphBtn) {
      var lbl = $('.sd-period-btn__label', graphBtn);
      if (lbl) lbl.textContent = GRAPH_LABELS[type] || 'Dashboard';
    }

    /* update dropdown active option */
    if (graphDropdown) {
      $$('.sd-period-option', graphDropdown).forEach(function (opt) {
        opt.classList.toggle('sd-period-option--active', opt.dataset.graph === type);
      });
    }

    /* toggle chart views */
    $$('.sd-chart-view').forEach(function (v) {
      v.classList.toggle('sd-chart-view--active', v.dataset.graph === type);
    });

    /* update title */
    if (chartTitle) chartTitle.textContent = GRAPH_LABELS[type] || 'Dashboard';

    /* lazy init */
    if (type === 'donut' && !donutChart) initDonutChart();
    if (type === 'bar' && !barChart) initBarChart();
    if (type === 'line' && !lineChart) initLineChart();
  }

  /* ==========================================================
     PERIOD DROPDOWN (custom dropdown, AJAX, no page reload)
     ========================================================== */
  var PERIOD_LABELS = { all: 'All Time', week: 'This Week', month: 'This Month', term: 'This Term', year: 'This Year' };

  /* Single place to flip a dropdown's state: aria-expanded, chevron, .open */
  function setDropdownState(btn, dd, open) {
    if (btn) {
      btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      btn.classList.toggle('sd-period-btn--open', open);
    }
    if (dd) dd.classList.toggle('open', open);
  }

  function togglePeriodDropdown() {
    var open = periodDropdown ? !periodDropdown.classList.contains('open') : false;
    setDropdownState(periodBtn, periodDropdown, open);
  }

  function closePeriodDropdown() {
    setDropdownState(periodBtn, periodDropdown, false);
  }

  function selectPeriod(period) {
    closePeriodDropdown();
    if (period === DATA.period) return;

    /* update active option */
    $$('.sd-period-option', periodDropdown).forEach(function (opt) {
      opt.classList.toggle('sd-period-option--active', opt.dataset.period === period);
    });

    /* update button text */
    if (periodBtn) {
      var lbl = $('.sd-period-btn__label', periodBtn);
      if (lbl) lbl.textContent = PERIOD_LABELS[period] || 'All Time';
    }

    fetchPeriod(period);
  }

  function fetchPeriod(period) {
    var url = '/school/' + DATA.schoolId + '?period=' + encodeURIComponent(period);

    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      if (data.stage_counts) DATA.stage = data.stage_counts;
      if (data.coverage_counts) DATA.coverage = data.coverage_counts;
      if (data.monthly_trends) DATA.monthly = data.monthly_trends;
      if (data.period) DATA.period = data.period;

      /* refresh active chart */
      if (activeGraph === 'donut') { if (donutChart) donutChart.destroy(); donutChart = null; initDonutChart(); }
      if (activeGraph === 'bar') { if (barChart) barChart.destroy(); barChart = null; initBarChart(); }
      if (activeGraph === 'line') { if (lineChart) lineChart.destroy(); lineChart = null; initLineChart(); }
    })
    .catch(function (err) {
      console.error('Period fetch failed:', err);
    });
  }

  /* ==========================================================
     NAV TAB SWITCHING (AJAX)
     ========================================================== */
  var currentTab = 'dashboard';

  function switchTab(tab) {
    if (tab === currentTab) return;
    var targetBtn = $('.sd-nav-link[data-tab="' + tab + '"]');
    if (targetBtn && targetBtn.dataset.locked) { showSubscriptionToast(); return; }
    currentTab = tab;

    /* update nav link active states */
    $$('.sd-nav-link').forEach(function (btn) {
      btn.classList.toggle('sd-nav-link--active', btn.dataset.tab === tab);
    });

    /* fetch sidebar students */
    fetchSidebarStudents(tab);

    /* if at-risk/results/classes tab, fetch fragment and swap mainContent */
    if (tab === 'at-risk') {
      fetchAtRiskFragment();
    } else if (tab === 'results') {
      fetchResultsFragment();
    } else if (tab === 'classes') {
      fetchClasses();
    } else {
      /* restore default panel */
      restoreDefaultPanel();
    }
  }

  function fetchSidebarStudents(tab) {
    if (!studentList) return;

    /* show loading */
    studentList.innerHTML = '<div class="sd-loading"><div class="sd-spinner"></div>Loading…</div>';

    var url = DATA.studentsUrl + '?tab=' + encodeURIComponent(tab) +
      (currentClassFilter ? '&class_id=' + encodeURIComponent(currentClassFilter) : '');

    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      var students = data.students || [];
      lastStudentTotal = data.total || students.length;
      if (sidebarCount) sidebarCount.textContent = data.total || students.length;

      if (students.length === 0) {
        studentList.innerHTML = '<div class="sd-student-list__empty"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:block;margin:0 auto 6px;"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>No students found</div>';
        return;
      }

      studentList.innerHTML = students.map(function (s) {
        var name = s.name || '';
        var initials = name.split(' ').map(function (w) { return w[0] || ''; }).join('').substring(0, 2).toUpperCase();
        var avatarColor = s.color || 'gray';
        return '<div class="sd-student-item" data-student-id="' + s.id + '" data-student-name="' + escHtml(name) + '" data-stage-color="' + avatarColor + '">' +
          '<div class="sd-student-item__avatar sd-student-item__avatar--' + avatarColor + '">' + escHtml(initials) + '</div>' +
          '<div class="sd-student-item__info">' +
            '<div class="sd-student-item__name">' + escHtml(name) + '</div>' +
            (s.class ? '<div class="sd-student-item__meta">' + escHtml(s.class) + '</div>' : '') +
          '</div>' +
        '</div>';
      }).join('');

      /* auto-select first student on Students tab */
      if (tab === 'students' && students.length > 0) {
        selectStudent(students[0].id);
      }

      /* re-apply any active search after a fresh render */
      applyStudentSearch();
    })
    .catch(function (err) {
      console.error('Sidebar fetch failed:', err);
      studentList.innerHTML = '<div class="sd-student-list__empty">Failed to load students</div>';
    });
  }

  function applyStudentSearch() {
    var search = $('#sdStudentSearch');
    if (!search) return;
    var q = search.value.trim().toLowerCase();
    var items = $$('.sd-student-item', studentList);
    var shown = 0;
    items.forEach(function (item) {
      var name = (item.dataset.studentName || '').toLowerCase();
      var match = !q || name.indexOf(q) !== -1;
      item.style.display = match ? '' : 'none';
      if (match) shown++;
    });
    var noMatch = $('#sdStudentSearchEmpty', studentList);
    if (!noMatch && items.length) {
      noMatch = document.createElement('div');
      noMatch.id = 'sdStudentSearchEmpty';
      noMatch.className = 'sd-student-list__empty';
      noMatch.textContent = 'No students match your search';
      studentList.appendChild(noMatch);
    }
    if (noMatch) noMatch.style.display = (items.length && shown === 0) ? 'block' : 'none';
    if (sidebarCount) {
      sidebarCount.textContent = q ? shown + ' of ' + lastStudentTotal : lastStudentTotal;
    }
  }

  function bindStudentSearch() {
    var search = $('#sdStudentSearch');
    if (!search) return;
    search.addEventListener('input', applyStudentSearch);
    search.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        exitSearchMode();
        if (sidebarFilter) sidebarFilter.focus();
      }
    });
    var close = $('#sdStudentSearchClose');
    if (close) close.onclick = exitSearchMode;
  }

  /* ==========================================================
     STUDENT DETAIL
     ========================================================== */
  function selectStudent(studentId) {
    /* mark currentTab away from at-risk/results so re-clicking the nav re-fetches */
    currentTab = 'student-detail';

    /* highlight active in sidebar */
    $$('.sd-student-item', studentList).forEach(function (item) {
      item.classList.toggle('sd-student-item--active', item.dataset.studentId == studentId);
    });

    var url = '/school/' + DATA.schoolId + '/dashboard/student/' + studentId;

    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      currentStudentData = data;
      renderStudentDetail(data);
    })
    .catch(function (err) {
      console.error('Student detail fetch failed:', err);
    });
  }

  function renderStudentDetail(data) {
    if (!mainContent || !data || !data.student) return;

    var s = data.student;
    var stages = data.stage_distribution || {};
    var coverage = data.coverage || {};
    var results = data.results || [];
    var monthlyData = data.monthly_data || [];

    /* --- stage distribution rows --- */
    var stageTotal = Object.values(stages).reduce(function (a, b) { return a + b; }, 0);
    var stageRows = Object.keys(stages).map(function (key) {
      var count = stages[key];
      var pct = stageTotal ? Math.round(count / stageTotal * 100) : 0;
      return '<div class="sd-detail-stage-row">' +
        '<span class="sd-badge sd-badge--' + key.toLowerCase().replace(' stage', '').replace(/\s+/g, '-') + '">' + escHtml(key) + '</span>' +
        '<span style="flex:1;margin:0 8px;height:6px;background:var(--sd-border);border-radius:3px;overflow:hidden;">' +
          '<span style="display:block;height:100%;width:' + pct + '%;background:' + stageColour(key) + ';border-radius:3px;"></span>' +
        '</span>' +
        '<span>' + count + ' (' + pct + '%)</span>' +
      '</div>';
    }).join('');

    /* --- coverage rows — route returns {test_type: {total, latest_stage, latest_date}} --- */
    var coverageRows = Object.keys(coverage).map(function (key) {
      var info = coverage[key];
      var count = (typeof info === 'object' && info !== null) ? info.total : info;
      var latestStage = (typeof info === 'object' && info !== null) ? info.latest_stage : null;
      return '<div class="sd-detail-coverage-row">' +
        '<span>' + escHtml(key) + '</span>' +
        '<span style="font-weight:600;">' + (count || 0) + ' tests' +
        '</span>' +
      '</div>';
    }).join('');

    /* --- result rows — route returns {test_type, score, max_score, stage, taken_at} --- */
    var resultRows = results.map(function (r) {
      var stageClass = 'sd-badge--' + ((r.stage || 'unknown').toLowerCase().replace(' stage', '').replace(/\s+/g, '-'));
      return '<tr>' +
        '<td>' + escHtml(r.test_type || 'Test') + '</td>' +
        '<td>' + (r.score || 0) + '/' + (r.max_score || 0) + '</td>' +
        '<td><span class="sd-badge ' + stageClass + '">' + escHtml((r.stage || 'Unknown').replace(' Stage', '')) + '</span></td>' +
        '<td>' + escHtml(r.taken_at || '') + '</td>' +
      '</tr>';
    }).join('');

    /* build the two-card layout — use s.name (flat field) */
    mainContent.innerHTML =
      /* Card 1: Progress chart */
      '<div class="sd-card sd-detail-progress-card">' +
        '<div class="sd-detail-identity">' +
          '<div class="sd-detail-name">' + escHtml(s.name || '') + '</div>' +
          '<div class="sd-detail-meta">' +
            '<span class="sd-detail-class" id="sdStudentClassLabel">' + escHtml(s.class || 'Unassigned') + '</span>' +
            (s.gender && s.gender !== '—' ? ' · ' + escHtml(s.gender) : '') +
          '</div>' +
        '</div>' +
        '<div class="sd-chart-section sd-chart-section--student">' +
          '<div class="sd-chart-empty" id="sdStudentChartEmpty">' +
            '<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="15" x2="21" y2="15"/><polyline points="8 12 11 9 14 12 17 7"/></svg>' +
            '<span>No chart data yet</span>' +
          '</div>' +
          '<div class="sd-chart-wrapper">' +
            '<div class="sd-chart-header">' +
              '<span class="sd-inner-title">Monthly Progress</span>' +
            '</div>' +
            '<canvas id="sdProgressCanvas"></canvas>' +
          '</div>' +
          '<div class="sd-legend sd-legend--student" id="sdStudentLegend">' +
            '<div class="sd-legend-summary__row">' +
              '<span class="sd-legend-summary__label">Latest</span>' +
              '<span class="sd-legend-summary__value" id="sdStudentLatest">—</span>' +
            '</div>' +
            '<div class="sd-legend-divider"></div>' +
            '<div class="sd-legend-summary__row">' +
              '<span class="sd-legend-summary__label">Average</span>' +
              '<span class="sd-legend-summary__value" id="sdStudentAvg">—</span>' +
            '</div>' +
            '<div class="sd-legend-divider"></div>' +
            '<div class="sd-legend-summary__trend" id="sdStudentTrend"></div>' +
            '<div class="sd-legend-summary__status" id="sdStudentStatus"></div>' +
          '</div>' +
        '</div>' +
      '</div>' +

      /* Card 2: Detail card */
      '<div class="sd-card sd-detail-card">' +
        '<div class="sd-detail-grid">' +
          '<div class="sd-detail-section">' +
            '<div style="font-weight:700;font-size:0.85rem;margin-bottom:10px;">Stage Distribution</div>' +
            (stageRows || '<div style="color:var(--sd-gray-light);font-size:0.85rem;">No data</div>') +
          '</div>' +
          '<div class="sd-detail-section">' +
            '<div style="font-weight:700;font-size:0.85rem;margin-bottom:10px;">Assessment Coverage</div>' +
            (coverageRows || '<div style="color:var(--sd-gray-light);font-size:0.85rem;">No data</div>') +
          '</div>' +
        '</div>' +
        '<div style="margin-top:16px;">' +
          '<div style="font-weight:700;font-size:0.85rem;margin-bottom:10px;">Test History (' + (data.total_results || results.length) + ')</div>' +
          '<div class="sd-results-scroll">' +
            '<table class="sd-table"><thead><tr><th>Type</th><th>Score</th><th>Stage</th><th>Date</th></tr></thead>' +
            '<tbody>' + (resultRows ||
              '<tr class="sd-table-empty"><td colspan="4">' +
                '<div class="sd-empty-state">' +
                  '<div class="sd-empty-state__icon"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg></div>' +
                  '<div class="sd-empty-state__title">No results</div>' +
                  '<div class="sd-empty-state__desc">This student has not completed an assessment yet.</div>' +
                '</div>' +
              '</td></tr>') + '</tbody></table>' +
          '</div>' +
        '</div>' +
      '</div>';

    /* init progress chart */
    initProgressChart(monthlyData);
  }

  /* ==========================================================
     RESTORE DEFAULT PANEL
     ========================================================== */
  function restoreDefaultPanel() {
    /* destroy student-specific chart */
    if (progressChart) { progressChart.destroy(); progressChart = null; }
    currentStudentData = null;

    /* restore saved HTML */
    if (savedMainHTML) {
      mainContent.innerHTML = savedMainHTML;
    }

    /* elements inside mainContent were recreated — refresh cached refs */
    refreshDomRefs();

    /* apply the user's selected graph view to the restored markup */
    $$('.sd-chart-view').forEach(function (v) {
      v.classList.toggle('sd-chart-view--active', v.dataset.graph === activeGraph);
    });
    if (chartTitle) chartTitle.textContent = GRAPH_LABELS[activeGraph] || 'Dashboard';

    /* re-init active chart */
    if (activeGraph === 'donut') initDonutChart();
    if (activeGraph === 'bar') initBarChart();
    if (activeGraph === 'line') initLineChart();

    /* re-bind graph + period toggles */
    bindGraphToggle();
    bindPeriodToggle();

    /* re-init at-risk card links + table sorting */
    initAtRiskCardLink();
    bindTableSort();

    /* chart-header class filter is inside re-rendered mainContent — repopulate + rebind */
    populateChartClassFilter();
  }

  /* ==========================================================
     AT-RISK FRAGMENT
     ========================================================== */
  function fetchAtRiskFragment(classGroup) {
    classGroup = (classGroup === undefined) ? riskClassFilter : classGroup;
    riskClassFilter = classGroup;
    mainContent.innerHTML = '<div class="sd-loading"><div class="sd-spinner"></div>Loading at-risk students…</div>';

    var url = '/school/' + DATA.schoolId + '/results?tab=at_risk&_fragment=1';
    if (classGroup) url += '&class_group=' + encodeURIComponent(classGroup);

    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function (res) { return res.text(); })
    .then(function (html) {
      if (html && html.trim().length > 10) {
        mainContent.innerHTML = html;
        initAtRiskCardLink();
        bindAtRiskFilters();
        bindTableSort();
      } else {
        mainContent.innerHTML = '<div class="sd-card sd-at-risk-empty">' +
          '<div class="sd-at-risk-empty__icon"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="M8 12l3 3 5-5"/></svg></div>' +
          '<h3 class="sd-at-risk-empty__title">No students at risk</h3>' +
          '<p class="sd-at-risk-empty__desc">All students are currently at Normal or Mild stage. Keep monitoring by uploading new assessments regularly.</p>' +
        '</div>';
      }
    })
    .catch(function (err) {
      console.error('At-risk fetch failed:', err);
      mainContent.innerHTML = '<div class="sd-card" style="text-align:center;padding:48px;color:var(--sd-gray-light);">Failed to load at-risk data</div>';
    });
  }

  /* ==========================================================
     RESULTS FRAGMENT (full results in the Results tab)
     ========================================================== */
  function resultsFragmentUrl(tab, classGroup, page) {
    var url = '/school/' + DATA.schoolId + '/results?tab=' + encodeURIComponent(tab) + '&_fragment=1&theme=sd';
    if (classGroup) url += '&class_group=' + encodeURIComponent(classGroup);
    if (page && page > 1) url += '&page=' + page;
    return url;
  }

  function fetchResultsFragment(tab, classGroup, page) {
    tab = tab || 'results';
    classGroup = (classGroup === undefined) ? resultsClassFilter : classGroup;
    page = page || 1;

    mainContent.innerHTML = '<div class="sd-loading"><div class="sd-spinner"></div>Loading results…</div>';

    fetch(resultsFragmentUrl(tab, classGroup, page), {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function (res) { return res.text(); })
    .then(function (html) {
      if (html && html.trim().length > 10) {
        mainContent.innerHTML = html;
        resultsTab = tab;
        resultsClassFilter = classGroup;
        bindResultsFragment();
        bindTableSort();
      } else {
        mainContent.innerHTML =
          '<div class="sd-card">' +
            '<div class="sd-empty-state">' +
              '<div class="sd-empty-state__icon"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg></div>' +
              '<div class="sd-empty-state__title">No results found</div>' +
              '<div class="sd-empty-state__desc">Results appear here once students complete an assessment.</div>' +
            '</div>' +
          '</div>';
      }
    })
    .catch(function (err) {
      console.error('Results fetch failed:', err);
      mainContent.innerHTML = '<div class="sd-card" style="text-align:center;padding:48px;color:var(--sd-gray-light);">Failed to load results</div>';
    });
  }

  /* --- results donut view (stage distribution — pie + key) --- */
  function initResultsDonutChart() {
    var card = $('.sd-results-chart-card');
    var canvas = $('#sdResultsDonut');
    var keyEl = $('#sdResultsStageKey');
    var totalEl = $('#sdResultsDonutTotal');
    if (!card || !canvas || !keyEl) return;
    if (resultsDonutChart) { resultsDonutChart.destroy(); resultsDonutChart = null; }

    var data = [];
    try {
      data = card.dataset.chart ? JSON.parse(card.dataset.chart) : [];
    } catch (e) {
      data = [];
    }

    var items = buildStageItems(data);
    if (!items.length) {
      keyEl.innerHTML = '<li class="sd-stage-key__item sd-stage-key__empty">No data</li>';
      if (totalEl) totalEl.textContent = '0';
      return;
    }
    resultsDonutChart = mountStageDoughnut(canvas, items, totalEl);
    renderStageKey(keyEl, items);
  }

  function initResultsBarChart() {
    var card = $('.sd-results-chart-card');
    var canvas = $('#sdResultsBar');
    if (!card || !canvas) return;
    if (resultsBarChart) { resultsBarChart.destroy(); resultsBarChart = null; }

    var data = {};
    try {
      data = card.dataset.coverage ? JSON.parse(card.dataset.coverage) : {};
    } catch (e) {
      data = {};
    }

    var labels = Object.keys(data);
    var values = labels.map(function (k) { return data[k]; });

    if (labels.length === 0 || values.every(function (v) { return v === 0; })) return;

    resultsBarChart = new Chart(canvas.getContext('2d'), {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          backgroundColor: COLORS.green,
          borderRadius: 6,
          maxBarThickness: 36
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: {
            beginAtZero: true,
            grid: { color: COLORS.border },
            ticks: { font: { family: 'Manrope' } }
          },
          y: {
            grid: { display: false },
            ticks: { font: { family: 'Manrope', weight: '600' } }
          }
        }
      }
    });
  }

  function initResultsLineChart() {
    var card = $('.sd-results-chart-card');
    var canvas = $('#sdResultsLine');
    if (!card || !canvas) return;
    if (resultsLineChart) { resultsLineChart.destroy(); resultsLineChart = null; }

    var data = {};
    try {
      data = card.dataset.monthly ? JSON.parse(card.dataset.monthly) : {};
    } catch (e) {
      data = {};
    }

    var labels = Object.keys(data);
    var values = labels.map(function (k) { return data[k]; });

    var avgEl = $('#sdResultsLineAvg');
    var monthsEl = $('#sdResultsLineMonths');
    if (monthsEl) monthsEl.textContent = labels.length;
    if (avgEl) {
      var sum = values.reduce(function (a, b) { return a + b; }, 0);
      avgEl.textContent = values.length ? Math.round(sum / values.length) : 0;
    }

    if (labels.length === 0 || values.every(function (v) { return v === 0; })) return;

    resultsLineChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          borderColor: COLORS.green,
          backgroundColor: areaFill(COLORS.green),
          fill: true,
          tension: 0.4,
          borderWidth: 2,
          borderCapStyle: 'round',
          pointBackgroundColor: COLORS.green,
          pointBorderColor: '#ffffff',
          pointRadius: 4,
          pointHoverRadius: 6
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: {
            beginAtZero: true,
            grid: { color: 'rgba(0,0,0,0.06)', drawTicks: false },
            border: { display: false },
            ticks: { font: { family: 'Manrope', size: 11 }, color: COLORS.text }
          },
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: { font: { family: 'Manrope', size: 11 }, color: COLORS.text }
          }
        }
      }
    });
  }

  var RESULTS_CHART_LABELS = { donut: 'Stage Distribution', bar: 'Assessment Coverage', line: 'Monthly Trends' };

  function switchResultsChart(type) {
    resultsChartType = type;

    var btn = $('#sdResultsGraphBtn');
    if (btn) {
      var lbl = $('.sd-period-btn__label', btn);
      if (lbl) lbl.textContent = RESULTS_CHART_LABELS[type] || 'Stage Distribution';
    }

    var dd = $('#sdResultsGraphDropdown');
    if (dd) {
      $$('.sd-period-option', dd).forEach(function (opt) {
        opt.classList.toggle('sd-period-option--active', opt.dataset.resultsChart === type);
      });
    }

    $$('#sdMainContent .sd-results-chart-view').forEach(function (v) {
      v.classList.toggle('sd-chart-view--active', v.dataset.resultsChart === type);
    });

    if (type === 'donut') initResultsDonutChart();
    if (type === 'bar') initResultsBarChart();
    if (type === 'line') initResultsLineChart();
  }

  function bindResultsFragment() {
    var filter = $('#sdResultsClassFilter');
    if (filter) {
      filter.onchange = function () {
        fetchResultsFragment(resultsTab, filter.value, 1);
      };
    }

    var rGraphBtn = $('#sdResultsGraphBtn');
    var rGraphDropdown = $('#sdResultsGraphDropdown');
    if (rGraphBtn && rGraphDropdown) {
      rGraphBtn.onclick = function (e) {
        e.stopPropagation();
        setDropdownState(rGraphBtn, rGraphDropdown, !rGraphDropdown.classList.contains('open'));
      };
      $$('.sd-period-option', rGraphDropdown).forEach(function (opt) {
        opt.onclick = function (e) {
          e.stopPropagation();
          switchResultsChart(opt.dataset.resultsChart);
          setDropdownState(rGraphBtn, rGraphDropdown, false);
        };
      });
    }

    $$('#sdMainContent .sd-pagination__link').forEach(function (link) {
      link.onclick = function (e) {
        e.preventDefault();
        fetchResultsFragment(resultsTab, resultsClassFilter, parseInt(link.dataset.page, 10));
      };
    });

    switchResultsChart(resultsChartType);
  }

  function bindAtRiskFilters() {
    var classSelect = $('#sdRiskClassFilter');
    if (classSelect) {
      classSelect.onchange = function () {
        fetchAtRiskFragment(classSelect.value);
      };
    }

    var pills = $$('#sdAtRiskFilters .sd-filter-pill');
    pills.forEach(function (pill) {
      pill.onclick = function () {
        pills.forEach(function (p) { p.classList.remove('sd-filter-pill--active'); });
        pill.classList.add('sd-filter-pill--active');
        var filter = pill.dataset.stageFilter;
        var rows = $$('#sdAtRiskFilters').length ? $$('.sd-at-risk-scroll tbody tr') : [];
        rows.forEach(function (row) {
          if (filter === 'all' || row.dataset.stage === filter) {
            row.style.display = '';
          } else {
            row.style.display = 'none';
          }
        });
      };
    });
  }

  function initAtRiskCardLink() {
    $$('.sd-vital-card[data-tab]').forEach(function (card) {
      card.classList.add('sd-vital-card--link');
      card.onclick = function () {
        var tab = card.dataset.tab;
        if (tab) switchTab(tab);
      };
      if (card.tagName === 'BUTTON') return;
      card.setAttribute('role', 'button');
      card.setAttribute('tabindex', '0');
      card.onkeydown = function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          card.onclick();
        }
      };
    });
  }

  /* ==========================================================
     CLASSES TAB
     ========================================================== */
  var currentClassId = null;

  function classesApi(url, options) {
    var opts = options || {};
    opts.headers = opts.headers || {};
    opts.headers['X-Requested-With'] = 'XMLHttpRequest';
    if (opts.method && opts.method.toUpperCase() !== 'GET') {
      opts.headers['X-CSRFToken'] = getCSRF();
    }
    if (opts.json) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    return fetch(url, opts).then(function (res) { return res.json(); });
  }

  function classLevelLabel(level) {
    if (!level) return '';
    return { jhs: 'JHS', shs: 'SHS', university: 'University' }[level] || level;
  }

  function renderClassCards(classes) {
    if (!mainContent) return;
    if (!classes || classes.length === 0) {
      mainContent.innerHTML =
        '<div class="sd-card">' +
          '<div class="sd-empty-state">' +
            '<div class="sd-empty-state__icon"><svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M22 10v6M2 10l10-5 10 5-10 5z"/><path d="M6 12v5c3 3 9 3 12 0v-5"/></svg></div>' +
            '<div class="sd-empty-state__title">No classes yet</div>' +
            '<div class="sd-empty-state__desc">Create a class to organise your students, then assign students during upload or from the student panel.</div>' +
            '<div class="sd-empty-state__action"><button class="sd-btn-solid" id="sdCreateClassEmptyBtn">Create Class</button></div>' +
          '</div>' +
        '</div>';
      var emptyBtn = $('#sdCreateClassEmptyBtn');
      if (emptyBtn) emptyBtn.onclick = openClassModal;
      return;
    }

    mainContent.innerHTML =
      '<div class="sd-card">' +
        '<div class="sd-card__header">' +
          '<div class="sd-card__title">Classes</div>' +
          '<div class="sd-class-toolbar">' +
            '<span class="sd-class-toolbar__count" id="sdClassCount">' + classes.length + ' class' + (classes.length === 1 ? '' : 'es') + '</span>' +
            '<div class="sd-class-search">' +
              '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>' +
              '<input type="search" id="sdClassSearch" placeholder="Search classes…" aria-label="Search classes">' +
            '</div>' +
            '<button class="sd-card__action" id="sdCreateClassBtn">' +
              '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" style="vertical-align:middle;margin-right:4px;"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>' +
              'New Class' +
            '</button>' +
          '</div>' +
        '</div>' +
        '<div class="sd-class-grid">' +
          classes.map(function (c) {
            var level = classLevelLabel(c.level);
            return '<div class="sd-class-card" data-class-id="' + c.id + '" data-class-name="' + escHtml(c.name) + '" data-class-level="' + escHtml(c.level || '') + '">' +
              '<div class="sd-class-card__top">' +
                '<div class="sd-class-card__meta">' +
                  '<div class="sd-class-card__name">' + escHtml(c.name) + '</div>' +
                  (level ? '<div class="sd-class-card__level">' + level + '</div>' : '') +
                '</div>' +
                '<div class="sd-class-menu">' +
                  '<button type="button" class="sd-class-menu__trigger" data-action="menu" aria-label="Class actions" aria-haspopup="true" aria-expanded="false">' +
                    '<svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="5" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="12" cy="19" r="1.7"/></svg>' +
                  '</button>' +
                  '<div class="sd-class-menu__dropdown" role="menu">' +
                    '<button type="button" class="sd-class-menu__item" role="menuitem" data-action="view"><svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>View Students</button>' +
                    '<button type="button" class="sd-class-menu__item" role="menuitem" data-action="add"><svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="8.5" cy="7" r="4"/><line x1="20" y1="8" x2="20" y2="14"/><line x1="23" y1="11" x2="17" y2="11"/></svg>Add Students</button>' +
                    '<button type="button" class="sd-class-menu__item" role="menuitem" data-action="rename"><svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg>Rename</button>' +
                    '<button type="button" class="sd-class-menu__item sd-class-menu__item--danger" role="menuitem" data-action="delete"><svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>Delete</button>' +
                  '</div>' +
                '</div>' +
              '</div>' +
              '<div class="sd-class-card__foot">' +
                '<div class="sd-class-card__count">' + (c.student_count || 0) + ' student' + ((c.student_count || 0) === 1 ? '' : 's') + (c.screened_count ? ' · ' + c.screened_count + ' screened' : '') + '</div>' +
              '</div>' +
            '</div>';
          }).join('') +
        '</div>' +
        '<div class="sd-class-no-match" id="sdClassNoMatch" style="display:none;">No classes match your search.</div>' +
      '</div>';

    var createBtn = $('#sdCreateClassBtn');
    if (createBtn) createBtn.onclick = openClassModal;

    var search = $('#sdClassSearch');
    if (search) {
      search.addEventListener('input', function () {
        var q = search.value.trim().toLowerCase();
        var shown = 0;
        $$('.sd-class-card').forEach(function (card) {
          var match = !q || (card.dataset.className || '').toLowerCase().indexOf(q) !== -1;
          card.style.display = match ? '' : 'none';
          if (match) shown++;
        });
        var count = $('#sdClassCount');
        if (count) count.textContent = shown + ' of ' + classes.length + ' class' + (classes.length === 1 ? '' : 'es');
        var noMatch = $('#sdClassNoMatch');
        if (noMatch) noMatch.style.display = shown ? 'none' : 'block';
      });
    }

    $$('.sd-class-card').forEach(function (card) {
      card.onclick = function (e) {
        var menuEl = e.target.closest('.sd-class-menu');
        if (menuEl) {
          e.stopPropagation();
          var trigger = e.target.closest('.sd-class-menu__trigger');
          var item = e.target.closest('.sd-class-menu__item');
          if (trigger) {
            toggleClassMenu(menuEl);
          } else if (item) {
            closeClassMenus();
            var action = item.dataset.action;
            var cid = card.dataset.classId;
            if (action === 'view') openClassDetail(cid);
            else if (action === 'add') openAddStudents(cid, card.dataset.className);
            else if (action === 'rename') openRenameModal(cid, card.dataset.className);
            else if (action === 'delete') openDeleteModal(cid, card.dataset.className);
          }
          return;
        }
        openClassDetail(card.dataset.classId);
      };
      card.addEventListener('mouseleave', closeClassMenus);
    });
  }

  function closeClassMenus() {
    $$('.sd-class-menu--open').forEach(function (m) {
      m.classList.remove('sd-class-menu--open');
      var trig = $('.sd-class-menu__trigger', m);
      if (trig) trig.setAttribute('aria-expanded', 'false');
    });
  }

  function toggleClassMenu(menu) {
    var isOpen = menu.classList.contains('sd-class-menu--open');
    closeClassMenus();
    if (!isOpen) {
      menu.classList.add('sd-class-menu--open');
      var trig = $('.sd-class-menu__trigger', menu);
      if (trig) trig.setAttribute('aria-expanded', 'true');
    }
  }

  document.addEventListener('click', function (e) {
    if (!e.target.closest('.sd-class-menu')) closeClassMenus();
  });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeClassMenus();
  });

  function fetchClasses() {
    if (mainContent) {
      mainContent.innerHTML = '<div class="sd-loading"><div class="sd-spinner"></div>Loading classes…</div>';
    }
    currentClassId = null;
    classesApi(DATA.classesUrl)
      .then(function (data) {
        if (data && data.error) {
          mainContent.innerHTML = '<div class="sd-card" style="text-align:center;padding:48px;color:var(--sd-gray-light);">' + escHtml(data.error) + '</div>';
          return;
        }
        renderClassCards(data.classes);
      })
      .catch(function (err) {
        console.error('Classes fetch failed:', err);
        mainContent.innerHTML = '<div class="sd-card" style="text-align:center;padding:48px;color:var(--sd-gray-light);">Failed to load classes</div>';
      });
  }

  function openClassDetail(classId) {
    currentClassId = classId;
    if (mainContent) {
      mainContent.innerHTML = '<div class="sd-loading"><div class="sd-spinner"></div>Loading class…</div>';
    }
    classesApi('/school/' + DATA.schoolId + '/dashboard/classes/' + classId)
      .then(function (data) {
        if (data && data.error) {
          mainContent.innerHTML = '<div class="sd-card" style="text-align:center;padding:48px;color:var(--sd-gray-light);">' + escHtml(data.error) + '</div>';
          return;
        }
        renderClassDetail(data);
      })
      .catch(function (err) {
        console.error('Class detail fetch failed:', err);
        mainContent.innerHTML = '<div class="sd-card" style="text-align:center;padding:48px;color:var(--sd-gray-light);">Failed to load class</div>';
      });
  }

  function renderClassDetail(data) {
    if (!mainContent) return;
    var cls = data.class || {};
    var students = data.students || [];

    var rows = students.length
      ? students.map(function (s) {
          return '<tr><td>' + escHtml(s.name) + '</td></tr>';
        }).join('')
      : '<tr class="sd-table-empty"><td colspan="1">' +
          '<div class="sd-empty-state">' +
            '<div class="sd-empty-state__icon"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg></div>' +
            '<div class="sd-empty-state__title">No students in this class yet</div>' +
            '<div class="sd-empty-state__desc">Add students to this class to track their wellbeing.</div>' +
          '</div>' +
        '</td></tr>';

    mainContent.innerHTML =
      '<div class="sd-card">' +
        '<div class="sd-card__header">' +
          '<button class="sd-card__action" id="sdClassBackBtn">' +
            '<svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:4px;"><polyline points="15 18 9 12 15 6"/></svg>' +
            'All Classes' +
          '</button>' +
          '<div class="sd-card__title">' + escHtml(cls.name || 'Class') + (cls.level ? ' · ' + classLevelLabel(cls.level) : '') + '</div>' +
          '<button class="sd-card__action" id="sdClassAddFromDetailBtn">+ Add Students</button>' +
        '</div>' +
        '<div class="sd-results-scroll">' +
          '<table class="sd-table"><thead><tr><th scope="col">Student</th></tr></thead>' +
          '<tbody>' + rows + '</tbody></table>' +
        '</div>' +
      '</div>';

    var back = $('#sdClassBackBtn');
    if (back) back.onclick = fetchClasses;
    var add = $('#sdClassAddFromDetailBtn');
    if (add) add.onclick = function () { openAddStudents(cls.id, cls.name); };
  }

  function submitCreate() {
    var nameInput = $('#sdClassName');
    var levelInput = $('#sdClassLevel');
    var name = nameInput ? nameInput.value.trim() : '';
    if (!name) {
      if (nameInput) nameInput.focus();
      return;
    }
    classesApi(DATA.classesUrl + '/create', {
      method: 'POST',
      json: { name: name, level: levelInput ? levelInput.value : '' }
    })
    .then(function (data) {
      if (data && data.error) {
        showToast(data.error || 'Could not create this class.', 'error');
        return;
      }
      closeOverlay('sdClassModalOverlay');
      showToast('Class created.', 'success');
      fetchClasses();
    })
    .catch(function (err) { console.error('Class create failed:', err); });
  }

  function openClassModal() {
    $('#sdClassName').value = '';
    $('#sdClassLevel').value = '';
    $('#sdClassModalTitle').textContent = 'New Class';
    $('#sdClassSubmit').textContent = 'Create Class';
    var levelRow = $('#sdClassLevelRow');
    if (levelRow) levelRow.style.display = '';
    var form = $('#sdClassForm');
    if (form) form.onsubmit = function (e) {
      e.preventDefault();
      submitCreate();
    };
    openOverlay('sdClassModalOverlay');
  }

  function openRenameModal(classId, currentName) {
    var title = $('#sdClassModalTitle');
    var nameInput = $('#sdClassName');
    var levelInput = $('#sdClassLevel');
    var submit = $('#sdClassSubmit');
    if (title) title.textContent = 'Rename Class';
    if (nameInput) nameInput.value = currentName || '';
    if (levelInput) levelInput.value = '';
    if (submit) submit.textContent = 'Save Name';
    var levelRow = $('#sdClassLevelRow');
    if (levelRow) levelRow.style.display = 'none';
    var form = $('#sdClassForm');
    if (form) form.onsubmit = function (e) {
      e.preventDefault();
      submitRename(classId, nameInput ? nameInput.value : '');
    };
    openOverlay('sdClassModalOverlay');
  }

  function submitRename(classId, name) {
    if (!name.trim()) return;
    classesApi('/school/' + DATA.schoolId + '/dashboard/classes/' + classId + '/rename', {
      method: 'POST',
      json: { name: name }
    })
    .then(function (data) {
      if (data && data.error) {
        showToast(data.error || 'Could not rename this class.', 'error');
        return;
      }
      closeOverlay('sdClassModalOverlay');
      showToast('Class renamed.', 'success');
      fetchClasses();
    })
    .catch(function (err) { console.error('Rename failed:', err); });
  }

  function openDeleteModal(classId, className) {
    var nameEl = $('#sdClassDeleteName');
    if (nameEl) nameEl.textContent = className || '';
    openOverlay('sdClassDeleteOverlay');
    var confirm = $('#sdClassDeleteConfirm');
    if (confirm) confirm.onclick = function () { submitDelete(classId); };
  }

  function submitDelete(classId) {
    classesApi('/school/' + DATA.schoolId + '/dashboard/classes/' + classId + '/delete', {
      method: 'POST'
    })
    .then(function (data) {
      if (data && data.error) {
        showToast(data.error || 'Could not delete this class.', 'error');
        return;
      }
      closeOverlay('sdClassDeleteOverlay');
      showToast('Class deleted.', 'success');
      fetchClasses();
    })
    .catch(function (err) { console.error('Delete failed:', err); });
  }

  function openAddStudents(classId, className) {
    var titleEl = $('#sdClassAddTitle');
    if (titleEl) titleEl.textContent = className || '';
    var list = $('#sdClassAddList');
    if (list) list.innerHTML = '<div class="sd-loading"><div class="sd-spinner"></div>Loading students…</div>';
    openOverlay('sdClassAddOverlay');

    classesApi('/school/' + DATA.schoolId + '/dashboard/classes/' + classId)
      .then(function (data) {
        var unassigned = (data && data.unassigned) || [];
        if (list) {
          if (unassigned.length === 0) {
            list.innerHTML = '<div style="text-align:center;padding:24px;color:var(--sd-gray-light);">All students are already assigned to a class.</div>';
          } else {
            list.innerHTML = unassigned.map(function (s) {
              return '<label class="sd-class-add-row">' +
                '<input type="checkbox" class="sd-class-add-check" value="' + s.id + '">' +
                '<span>' + escHtml(s.name) + '</span>' +
              '</label>';
            }).join('');
          }
        }
        var confirm = $('#sdClassAddConfirm');
        if (confirm) confirm.onclick = function () { submitAddStudents(classId); };
      })
      .catch(function (err) {
        console.error('Add-students load failed:', err);
        if (list) list.innerHTML = '<div style="text-align:center;padding:24px;color:var(--sd-gray-light);">Failed to load students</div>';
      });
  }

  function submitAddStudents(classId) {
    var checks = $$('.sd-class-add-check:checked');
    if (checks.length === 0) {
      showToast('Select at least one student to add.', 'warning');
      return;
    }
    var ids = checks.map(function (c) { return parseInt(c.value, 10); });
    classesApi('/school/' + DATA.schoolId + '/dashboard/classes/' + classId + '/add-students', {
      method: 'POST',
      json: { student_ids: ids }
    })
    .then(function (data) {
      if (data && data.error) {
        showToast(data.error || 'Could not add students.', 'error');
        return;
      }
      closeOverlay('sdClassAddOverlay');
      showToast(checks.length + ' student' + (checks.length === 1 ? '' : 's') + ' added.', 'success');
      if (currentClassId == classId) {
        openClassDetail(classId);
      } else {
        fetchClasses();
      }
    })
    .catch(function (err) { console.error('Add students failed:', err); });
  }

  /* ==========================================================
     MODAL HELPERS (.open class toggle per CSS)
     ========================================================== */
  function openOverlay(id) {
    var el = document.getElementById(id);
    if (el) el.classList.add('open');
  }

  function closeOverlay(id) {
    var el = document.getElementById(id);
    if (el) el.classList.remove('open');
  }

  /* ==========================================================
     CLAIM CODES MODAL
     ========================================================== */
  function openClaimCodes() {
    var grid = $('#sdClaimGrid');
    var header = $('#sdClaimHeader');
    var urlCode = $('#sdClaimUrlCode');
    openOverlay('sdClaimModalOverlay');
    if (grid) grid.innerHTML = '<div class="sd-loading"><div class="sd-spinner"></div>Loading claim codes…</div>';

    fetch(DATA.claimCodesUrl, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      var students = data.students || [];
      var schoolName = data.school_name || '';
      var claimUrl = data.claim_url || '';
      var totalStudents = data.total_students || 0;

      if (urlCode) urlCode.textContent = claimUrl;

      if (students.length === 0) {
        if (header) header.innerHTML = '';
        if (urlCode) urlCode.textContent = '';
        var copyRow = $('.sd-cc-copy-row');
        if (copyRow) copyRow.style.display = 'none';
        if (totalStudents === 0) {
          if (grid) grid.innerHTML =
            '<div class="sd-cc-empty">' +
              '<div class="sd-cc-empty__icon">' +
                '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
                  '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>' +
                  '<polyline points="14 2 14 8 20 8"/>' +
                  '<line x1="16" y1="13" x2="8" y2="13"/>' +
                  '<line x1="16" y1="17" x2="8" y2="17"/>' +
                  '<polyline points="10 9 9 9 8 9"/>' +
                '</svg>' +
              '</div>' +
              '<div class="sd-cc-empty__title">No students uploaded yet</div>' +
              '<div class="sd-cc-empty__desc">Upload students first to generate claim codes for them.</div>' +
              '<button class="sd-btn-solid" onclick="closeOverlay(\'sdClaimModalOverlay\');uploadOrToast();">' +
                '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:6px;"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>' +
                'Upload Students' +
              '</button>' +
            '</div>';
        } else {
          if (grid) grid.innerHTML =
            '<div class="sd-cc-empty">' +
              '<div class="sd-cc-empty__icon">' +
                '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
                  '<polyline points="20 6 9 17 4 12"/>' +
                '</svg>' +
              '</div>' +
              '<div class="sd-cc-empty__title">All accounts claimed</div>' +
              '<div class="sd-cc-empty__desc">Every student has activated their account, so there are no claim codes left to print. New students will receive a claim code when you upload them.</div>' +
            '</div>';
        }
        return;
      }

      if (header) header.innerHTML =
        '<div class="sd-cc-header__icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg></div>' +
        '<div class="sd-cc-header__text">' +
          '<div class="sd-cc-header__name">' + escHtml(schoolName) + '</div>' +
          '<div class="sd-cc-header__count">' + students.length + ' unclaimed account' + (students.length !== 1 ? 's' : '') + '</div>' +
        '</div>';

      var copyRow2 = $('.sd-cc-copy-row');
      if (copyRow2) copyRow2.style.display = '';

      if (grid) {
        grid.innerHTML = students.map(function (s) {
          var code = s.claim_code || '——';
          var name = s.name || 'Unnamed';
          var meta = (s.username ? '@' + escHtml(s.username) : '') + (s.class_group ? ' · ' + escHtml(s.class_group) : '');
          return '<div class="sd-cc-slip">' +
            '<div class="sd-cc-slip__school">' + escHtml(schoolName) + '</div>' +
            '<div class="sd-cc-slip__name">' + escHtml(name) + '</div>' +
            (meta ? '<div class="sd-cc-slip__meta">' + meta + '</div>' : '') +
            '<hr class="sd-cc-slip__divider">' +
            '<div class="sd-cc-slip__code-label">Claim Code</div>' +
            '<div class="sd-cc-slip__code">' + escHtml(code) + '</div>' +
            '<div class="sd-cc-slip__url">Go to <strong>' + escHtml(claimUrl) + '</strong> and enter this code.</div>' +
          '</div>';
        }).join('');
      }
    })
    .catch(function (err) {
      console.error('Claim codes fetch failed:', err);
      if (grid) grid.innerHTML = '<div class="sd-loading" style="color:var(--sd-stage-clinical, #d64541);">Failed to load claim codes</div>';
    });
  }

  /* ==========================================================
     UPLOAD MODAL
     ========================================================== */
  function openUploadModal() {
    populateUploadClassDropdown();
    openOverlay('uploadModalOverlay');
  }

  function showToast(message, type) {
    var toast = document.createElement('div');
    toast.className = 'flash-toast' + (type ? ' ' + type : '');
    toast.setAttribute('role', (type === 'error' || type === 'danger') ? 'alert' : 'status');
    toast.innerHTML = '<span>' + message + '</span>';
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'flash-toast__close';
    close.setAttribute('aria-label', 'Dismiss notification');
    close.textContent = '×';
    close.addEventListener('click', function (e) {
      e.stopPropagation();
      dismissToast(toast);
    });
    toast.appendChild(close);
    var stack = document.querySelector('.flash-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'flash-stack';
      stack.setAttribute('role', 'status');
      stack.setAttribute('aria-live', 'polite');
      document.body.appendChild(stack);
    }
    stack.appendChild(toast);
    toast.addEventListener('click', function () { dismissToast(toast); });
    setTimeout(function () { dismissToast(toast); }, 4500);
    return toast;
  }

  function dismissToast(toast) {
    toast.style.transition = 'opacity 180ms ease, transform 180ms cubic-bezier(.23,1,.32,1)';
    toast.style.opacity = '0';
    toast.style.transform = 'translateX(16px)';
    setTimeout(function () { toast.remove(); }, 180);
  }

  function showSubscriptionToast() {
    var toast = showToast('This feature requires an active subscription. <strong>Tap here to subscribe now.</strong>', 'warning');
    toast.addEventListener('click', function () { initPaystack(); });
  }

  function closeUploadModal() {
    closeOverlay('uploadModalOverlay');
    var progress = $('#uploadProgress');
    if (progress) progress.style.display = 'none';
    var bar = $('#uploadProgressBar');
    if (bar) bar.style.width = '0%';
  }

  function handleUploadFile(file) {
    if (!file) return;
    var progress = $('#uploadProgress');
    var bar = $('#uploadProgressBar');
    var status = $('#uploadStatus');
    if (progress) progress.style.display = 'block';
    if (status) status.textContent = 'Uploading ' + file.name + '…';
    if (bar) bar.style.width = '30%';

    var formData = new FormData();
    formData.append('file', file);

    var classSelect = $('#uploadClassSelect');
    var targetClass = classSelect ? classSelect.value : '';
    if (targetClass) formData.append('target_class', targetClass);

    var uploadUrl = '/school/' + DATA.schoolId + '/upload-students';

    fetch(uploadUrl, {
      method: 'POST',
      body: formData,
      headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCSRF() }
    })
    .then(function (res) {
      if (!res.ok) return res.json().catch(function () { return {}; }).then(function (d) {
        d.__status = res.status;
        return d;
      });
      return res.json();
    })
    .then(function (data) {
      if (data && data.__status >= 400) {
        if (bar) bar.style.width = '0%';
        if (status) status.textContent = data.error || 'Upload failed. Please try again.';
        return;
      }
      if (data && data.redirect) {
        location.href = data.redirect;
        return;
      }
      if (bar) bar.style.width = '100%';
      if (status) status.textContent = data.message || 'Upload complete!';
      setTimeout(function () { location.reload(); }, 1500);
    })
    .catch(function (err) {
      console.error('Upload failed:', err);
      if (status) status.textContent = 'Upload failed. Please try again.';
      if (bar) bar.style.width = '0%';
    });
  }

  function populateUploadClassDropdown() {
    var select = $('#uploadClassSelect');
    if (!select) return;
    classesApi(DATA.classesUrl)
      .then(function (data) {
        var classes = (data && data.classes) || [];
        var options = '<option value="">— Unassigned —</option>';
        if (classes.length === 0) {
          options += '<option value="" disabled>No classes yet — create one in the Classes tab first</option>';
        } else {
          options += classes.map(function (c) {
            return '<option value="' + c.id + '">' + escHtml(c.name) + '</option>';
          }).join('');
        }
        select.innerHTML = options;

        var noClassesRow = $('#uploadNoClassesRow');
        if (noClassesRow) noClassesRow.style.display = classes.length === 0 ? '' : 'none';
        var noClassesBtn = $('#uploadNoClassesBtn');
        if (noClassesBtn) {
          noClassesBtn.onclick = function () {
            closeOverlay('uploadModalOverlay');
            switchTab('classes');
          };
        }
      })
      .catch(function (err) { console.error('Class dropdown load failed:', err); });
  }

  /* ==========================================================
     COPY LINK
     ========================================================== */
  function copyRegLink() {
    var linkEl = $('#sdRegLink');
    if (!linkEl) return;
    var text = linkEl.textContent || linkEl.innerText;

    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(function () {
        var btn = $('#sdCopyLink');
        if (btn) { btn.textContent = 'Copied!'; setTimeout(function () { btn.textContent = 'Copy'; }, 2000); }
      });
    } else {
      var ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      var btn = $('#sdCopyLink');
      if (btn) { btn.textContent = 'Copied!'; setTimeout(function () { btn.textContent = 'Copy'; }, 2000); }
    }
  }

  /* ==========================================================
     PAYSTACK PAYMENT
     ========================================================== */
  function initPaystack() {
    if (!DATA.paystackKey || !window.PaystackPop) {
      showToast('Payments are not set up yet. Please contact support.', 'error');
      return;
    }

    var handler = PaystackPop.setup({
      key: DATA.paystackKey,
      email: DATA.email,
      amount: DATA.amount * 100,
      currency: DATA.currency,
      ref: 'SESASub_' + DATA.schoolId + '_' + Date.now(),
      testMode: DATA.testMode,
      callback: function (response) {
        fetch(DATA.verifyUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest'
          },
          body: JSON.stringify({ reference: response.reference })
        })
        .then(function (res) { return res.json(); })
        .then(function (data) {
          if (data.success) {
            showToast('Payment successful! Your subscription is now active.', 'success');
            setTimeout(function () { location.reload(); }, 1500);
          } else {
            showToast('We could not verify your payment. Please contact support.', 'error');
          }
        })
        .catch(function (err) {
          console.error('Verification failed:', err);
          showToast('We could not verify your payment. Please contact support.', 'error');
        });
      },
      onClose: function () {}
    });
    handler.openIframe();
  }

  /* ==========================================================
     PROFILE DROPDOWN
     ========================================================== */
  function toggleProfileDropdown(e) {
    if (e.target.closest('.sd-profile-dropdown')) return;
    e.stopPropagation();
    var dd = profileDropdown ? $('.sd-profile-dropdown', profileDropdown) : null;
    if (dd) {
      var open = dd.classList.toggle('open');
      if (profileDropdown) {
        profileDropdown.setAttribute('aria-expanded', open ? 'true' : 'false');
        profileDropdown.classList.toggle('sd-topnav__user--open', open);
      }
    }
  }

  function closeProfileDropdown() {
    var dd = profileDropdown ? $('.sd-profile-dropdown', profileDropdown) : null;
    if (dd) dd.classList.remove('open');
    if (profileDropdown) {
      profileDropdown.setAttribute('aria-expanded', 'false');
      profileDropdown.classList.remove('sd-topnav__user--open');
    }
  }

  /* ==========================================================
     DOM REFS (re-query after mainContent is re-rendered)
     ========================================================== */
  function refreshDomRefs() {
    sidebar          = $('#sdSidebar');
    studentList      = $('#sdStudentList');
    emptySidebar     = $('#sdEmptySidebar');
    sidebarCount     = $('#sdSidebarCount');
    sidebarFilterWrap = $('#sdSidebarFilter');
    sidebarFilter     = $('#sdClassFilter');
    chartClassFilter  = $('#sdChartClassFilter');
    mainContent      = $('#sdMainContent');
    graphToggle      = $('#sdGraphToggle');
    graphBtn         = $('#sdGraphBtn');
    graphDropdown    = $('#sdGraphDropdown');
    periodBtn        = $('#sdPeriodBtn');
    periodDropdown   = $('#sdPeriodDropdown');
    chartTitle       = $('#sdChartTitle');
    chartEmpty       = $('#sdChartEmpty');
    profileDropdown  = $('#sdProfileDropdown');
  }

  /* ==========================================================
     EVENT BINDING
     ========================================================== */

  function bindGraphToggle() {
    if (!graphBtn || !graphDropdown) return;
    graphBtn.onclick = function (e) {
      e.stopPropagation();
      var willOpen = !graphDropdown.classList.contains('open');
      setDropdownState(graphBtn, graphDropdown, willOpen);
      setDropdownState(periodBtn, periodDropdown, false);
    };
    $$('.sd-period-option', graphDropdown).forEach(function (opt) {
      opt.onclick = function (e) {
        e.stopPropagation();
        switchGraph(opt.dataset.graph);
        setDropdownState(graphBtn, graphDropdown, false);
      };
    });
  }

  function bindPeriodToggle() {
    if (!periodBtn || !periodDropdown) return;
    periodBtn.onclick = function (e) {
      e.stopPropagation();
      var willOpen = !periodDropdown.classList.contains('open');
      setDropdownState(periodBtn, periodDropdown, willOpen);
      setDropdownState(graphBtn, graphDropdown, false);
    };
    $$('.sd-period-option', periodDropdown).forEach(function (opt) {
      opt.onclick = function (e) {
        e.stopPropagation();
        selectPeriod(opt.dataset.period);
      };
    });
  }

  /* ==========================================================
     SORTABLE TABLE
     ========================================================== */
  function parseDateCell(text) {
    var m = String(text || '').trim().match(/^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$/);
    if (!m) return null;
    var months = { jan: 0, feb: 1, mar: 2, apr: 3, may: 4, jun: 5, jul: 6, aug: 7, sep: 8, oct: 9, nov: 10, dec: 11 };
    var mi = months[String(m[2]).toLowerCase().substring(0, 3)];
    if (mi === undefined) return null;
    return new Date(parseInt(m[3], 10), mi, parseInt(m[1], 10)).getTime();
  }

  function cellSortValue(td) {
    var pct = $('.sd-score-cell__pct', td);
    if (pct) return { v: parseFloat(pct.textContent) || 0, t: 'num' };
    var text = (td.textContent || '').trim();
    var num = parseFloat(String(text).replace(/,/g, ''));
    if (!isNaN(num) && /^-?[\d.,\s]+%?$/.test(text)) return { v: num, t: 'num' };
    var d = parseDateCell(text);
    if (d !== null) return { v: d, t: 'date' };
    return { v: text.toLowerCase(), t: 'str' };
  }

  function sortTable(th, index) {
    var table = th.closest('table');
    if (!table) return;
    var tbody = table.querySelector('tbody');
    if (!tbody) return;
    var rows = Array.from(tbody.querySelectorAll('tr'));
    if (rows.length <= 1) return;
    if (rows.some(function (r) { return r.querySelector('td[colspan]'); })) return;

    var headers = Array.from(table.querySelectorAll('thead th'));
    var dir = th.getAttribute('aria-sort') === 'ascending' ? 'descending' : 'ascending';

    var sortables = rows.map(function (row, i) {
      var td = row.querySelectorAll('td')[index];
      var sv = td ? cellSortValue(td) : { v: '', t: 'str' };
      return { row: row, v: sv.v, t: sv.t, i: i };
    });

    sortables.sort(function (a, b) {
      if (a.t === b.t && (a.t === 'num' || a.t === 'date')) return a.v - b.v;
      var av = String(a.v);
      var bv = String(b.v);
      return av < bv ? -1 : av > bv ? 1 : a.i - b.i;
    });

    if (dir === 'descending') sortables.reverse();

    sortables.forEach(function (s) { tbody.appendChild(s.row); });

    headers.forEach(function (h) {
      h.setAttribute('aria-sort', h === th ? dir : 'none');
    });
  }

  function bindTableSort() {
    $$('.sd-table[data-sortable] thead th').forEach(function (th, index) {
      th.setAttribute('tabindex', '0');
      th.setAttribute('aria-sort', 'none');
      th.classList.add('sd-table__sortable');
      var run = function () { sortTable(th, index); };
      th.onclick = run;
      th.onkeydown = function (e) {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); run(); }
      };
    });
  }

  function bindEvents() {
    /* nav tabs */
    $$('.sd-nav-link').forEach(function (btn) {
      btn.onclick = function () { switchTab(btn.dataset.tab); };
    });

    /* in-app tab actions (View all, Full Results, etc.) */
    $$('.sd-card__action[data-tab], .sd-action-list__item[data-tab]').forEach(function (el) {
      el.onclick = function () { switchTab(el.dataset.tab); };
    });

    /* graph + period toggles */
    bindGraphToggle();
    bindPeriodToggle();

    /* close dropdowns on outside click */
    document.addEventListener('click', function (e) {
      if (periodDropdown && periodDropdown.classList.contains('open') &&
          !periodDropdown.contains(e.target) && e.target !== periodBtn) {
        closePeriodDropdown();
      }
      if (graphDropdown && graphDropdown.classList.contains('open') &&
          !graphDropdown.contains(e.target) && e.target !== graphBtn) {
        setDropdownState(graphBtn, graphDropdown, false);
      }
      var rBtn = $('#sdResultsGraphBtn');
      var rDD = $('#sdResultsGraphDropdown');
      if (rDD && rBtn && rDD.classList.contains('open') && !rDD.contains(e.target) && e.target !== rBtn) {
        setDropdownState(rBtn, rDD, false);
      }
    });

    /* sidebar student clicks (delegated) */
    if (studentList) {
      studentList.onclick = function (e) {
        var item = e.target.closest('.sd-student-item');
        if (item && item.dataset.studentId) {
          selectStudent(item.dataset.studentId);
        }
      };
    }

    /* profile dropdown */
    if (profileDropdown) {
      profileDropdown.onclick = toggleProfileDropdown;
      profileDropdown.onkeydown = function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          toggleProfileDropdown(e);
        }
        if (e.key === 'Escape' && $('.sd-profile-dropdown', profileDropdown)) {
          closeProfileDropdown();
          profileDropdown.focus();
        }
      };
    }

    /* close profile dropdown on outside click */
    document.addEventListener('click', function (e) {
      var dd = profileDropdown ? $('.sd-profile-dropdown', profileDropdown) : null;
      if (dd && dd.classList.contains('open') && !profileDropdown.contains(e.target)) {
        closeProfileDropdown();
      }
    });

    /* close all dropdowns on Escape */
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'Escape') return;
      if (periodDropdown && periodDropdown.classList.contains('open')) closePeriodDropdown();
      if (graphDropdown && graphDropdown.classList.contains('open')) setDropdownState(graphBtn, graphDropdown, false);
      var rBtn = $('#sdResultsGraphBtn');
      var rDD = $('#sdResultsGraphDropdown');
      if (rDD && rBtn && rDD.classList.contains('open')) setDropdownState(rBtn, rDD, false);
      var pd = profileDropdown ? $('.sd-profile-dropdown', profileDropdown) : null;
      if (pd && pd.classList.contains('open')) closeProfileDropdown();
    });

    /* upload */
    var uploadBtn = $('#uploadBtn');
    if (uploadBtn) uploadBtn.onclick = function () {
      if (DATA.uploadEnabled) {
        openUploadModal();
      } else {
        showSubscriptionToast();
      }
    };

    var uploadModalClose = $('#uploadModalClose');
    if (uploadModalClose) uploadModalClose.onclick = closeUploadModal;

    var uploadOverlay = $('#uploadModalOverlay');
    if (uploadOverlay) {
      uploadOverlay.onclick = function (e) {
        if (e.target === uploadOverlay) closeUploadModal();
      };
    }

    /* upload zone drag & drop */
    var uploadZone = $('#uploadZone');
    var uploadFile = $('#uploadFile');
    if (uploadZone && uploadFile) {
      uploadZone.onclick = function () { uploadFile.click(); };
      uploadZone.ondragover = function (e) { e.preventDefault(); uploadZone.style.borderColor = 'var(--sd-green)'; };
      uploadZone.ondragleave = function () { uploadZone.style.borderColor = ''; };
      uploadZone.ondrop = function (e) {
        e.preventDefault();
        uploadZone.style.borderColor = '';
        if (e.dataTransfer.files.length > 0) handleUploadFile(e.dataTransfer.files[0]);
      };
      uploadFile.onchange = function () {
        if (uploadFile.files.length > 0) handleUploadFile(uploadFile.files[0]);
      };
    }

    /* claim codes */
    var claimBtn = $('#sdClaimCodesBtn');
    if (claimBtn) claimBtn.onclick = openClaimCodes;
    var claimModalClose = $('#sdClaimModalClose');
    if (claimModalClose) claimModalClose.onclick = function () { closeOverlay('sdClaimModalOverlay'); };

    var claimOverlay = $('#sdClaimModalOverlay');
    if (claimOverlay) {
      claimOverlay.onclick = function (e) {
        if (e.target === claimOverlay) closeOverlay('sdClaimModalOverlay');
      };
    }

    var claimCopyBtn = $('#sdClaimCopyBtn');
    if (claimCopyBtn) claimCopyBtn.onclick = function () {
      var codeEl = $('#sdClaimUrlCode');
      if (codeEl && navigator.clipboard) {
        var text = codeEl.textContent || codeEl.innerText;
        navigator.clipboard.writeText(text).then(function () {
          claimCopyBtn.textContent = 'Copied!';
          setTimeout(function () { claimCopyBtn.textContent = 'Copy'; }, 2000);
        });
      }
    };

    /* QR modal */
    var qrBtn = $('#sdQrBtn');
    if (qrBtn) qrBtn.onclick = function () { openOverlay('sdQrModalOverlay'); };
    var qrModalClose = $('#sdQrModalClose');
    if (qrModalClose) qrModalClose.onclick = function () { closeOverlay('sdQrModalOverlay'); };

    var qrOverlay = $('#sdQrModalOverlay');
    if (qrOverlay) {
      qrOverlay.onclick = function (e) {
        if (e.target === qrOverlay) closeOverlay('sdQrModalOverlay');
      };
    }

    var qrCopyBtn = $('#sdQrCopyBtn');
    if (qrCopyBtn) qrCopyBtn.onclick = function () {
      var codeEl = $('#sdQrLink');
      if (codeEl && navigator.clipboard) {
        var text = codeEl.textContent || codeEl.innerText;
        navigator.clipboard.writeText(text).then(function () {
          qrCopyBtn.textContent = 'Copied!';
          setTimeout(function () { qrCopyBtn.textContent = 'Copy'; }, 2000);
        });
      }
    };

    /* class modal bindings */
    var classModalClose = $('#sdClassModalClose');
    if (classModalClose) classModalClose.onclick = function () { closeOverlay('sdClassModalOverlay'); };

    var classModalOverlay = $('#sdClassModalOverlay');
    if (classModalOverlay) {
      classModalOverlay.onclick = function (e) {
        if (e.target === classModalOverlay) closeOverlay('sdClassModalOverlay');
      };
    }

    var classForm = $('#sdClassForm');
    if (classForm) classForm.onsubmit = function (e) {
      e.preventDefault();
      var submit = $('#sdClassSubmit');
      if (submit && submit.textContent.trim() === 'Create Class') {
        submitCreate();
      } else {
        var cid = classForm.dataset.classId;
        if (cid) submitRename(parseInt(cid, 10), $('#sdClassName').value);
      }
    };

    var classDeleteClose = $('#sdClassDeleteClose');
    if (classDeleteClose) classDeleteClose.onclick = function () { closeOverlay('sdClassDeleteOverlay'); };

    var classDeleteCancel = $('#sdClassDeleteCancel');
    if (classDeleteCancel) classDeleteCancel.onclick = function () { closeOverlay('sdClassDeleteOverlay'); };

    var classDeleteOverlay = $('#sdClassDeleteOverlay');
    if (classDeleteOverlay) {
      classDeleteOverlay.onclick = function (e) {
        if (e.target === classDeleteOverlay) closeOverlay('sdClassDeleteOverlay');
      };
    }

    var classAddClose = $('#sdClassAddClose');
    if (classAddClose) classAddClose.onclick = function () { closeOverlay('sdClassAddOverlay'); };

    var classAddCancel = $('#sdClassAddCancel');
    if (classAddCancel) classAddCancel.onclick = function () { closeOverlay('sdClassAddOverlay'); };

    var classAddOverlay = $('#sdClassAddOverlay');
    if (classAddOverlay) {
      classAddOverlay.onclick = function (e) {
        if (e.target === classAddOverlay) closeOverlay('sdClassAddOverlay');
      };
    }

    /* copy link */
    var copyBtn = $('#sdCopyLink');
    if (copyBtn) copyBtn.onclick = copyRegLink;

    /* paystack */
    var payBtn = $('#sdPayBtn');
    if (payBtn) payBtn.onclick = initPaystack;

    /* at-risk card */
    initAtRiskCardLink();

    /* sortable tables (Recent Results + any data-sortable table) */
    bindTableSort();
  }

  /* ==========================================================
     CLASS FILTERS (sidebar + chart header stay in sync)
     ========================================================== */
  function fillClassSelects(classes) {
    cachedClasses = classes;
    if (sidebarFilter) {
      sidebarFilter.innerHTML = '<option value="">All Classes</option>' +
        classes.map(function (c) {
          return '<option value="' + c.id + '">' + escHtml(c.name) + '</option>';
        }).join('') +
        '<option value="' + SEARCH_OPTION + '">Search students…</option>';
      sidebarFilter.value = currentClassFilter;
    }
    if (chartClassFilter) {
      chartClassFilter.innerHTML = '<option value="">All Classes</option>' +
        classes.map(function (c) {
          return '<option value="' + c.id + '">' + escHtml(c.name) + '</option>';
        }).join('');
      chartClassFilter.value = currentClassFilter;
    }
  }

  function populateChartClassFilter() {
    if (!chartClassFilter) return;
    if (cachedClasses.length > 0) {
      fillClassSelects(cachedClasses);
    } else {
      classesApi(DATA.classesUrl)
        .then(function (data) {
          fillClassSelects((data && data.classes) || []);
        })
        .catch(function (err) { console.error('Class filter load failed:', err); });
    }
    chartClassFilter.onchange = function () {
      setClassFilter(chartClassFilter.value);
    };
  }

  function setClassFilter(value) {
    var v = value || '';
    if (sidebarFilter && sidebarFilter.hidden) {
      /* leaving search mode — apply the chosen class instead of restoring the stale one */
      prevClassFilter = v;
      exitSearchMode();
      return;
    }
    currentClassFilter = v;
    if (sidebarFilter) sidebarFilter.value = v;
    if (chartClassFilter) chartClassFilter.value = v;
    fetchSidebarStudents(currentTab);
  }

  function initSidebarFilter() {
    if (!sidebarFilter) return;
    sidebarFilter.onchange = function () {
      if (sidebarFilter.value === SEARCH_OPTION) {
        enterSearchMode();
      } else {
        setClassFilter(sidebarFilter.value);
      }
    };
    populateChartClassFilter();
    classesApi(DATA.classesUrl)
      .then(function (data) {
        fillClassSelects((data && data.classes) || []);
      })
      .catch(function (err) {
        console.error('Class filter load failed:', err);
        if (sidebarFilterWrap) sidebarFilterWrap.style.display = 'none';
      });
  }

  function enterSearchMode() {
    var searchWrap = $('#sdStudentSearchWrap');
    var search = $('#sdStudentSearch');
    prevClassFilter = currentClassFilter;
    currentClassFilter = '';
    sidebarFilter.value = '';
    sidebarFilter.hidden = true;
    if (chartClassFilter) chartClassFilter.value = '';
    if (searchWrap) {
      searchWrap.hidden = false;
      requestAnimationFrame(function () {
        searchWrap.classList.add('sd-student-search--open');
      });
    }
    fetchSidebarStudents(currentTab);
    if (search) search.focus();
  }

  function exitSearchMode() {
    var searchWrap = $('#sdStudentSearchWrap');
    var search = $('#sdStudentSearch');
    if (search) search.value = '';
    if (searchWrap) {
      searchWrap.classList.remove('sd-student-search--open');
      searchWrap.hidden = true;
    }
    sidebarFilter.hidden = false;
    currentClassFilter = prevClassFilter || '';
    prevClassFilter = '';
    sidebarFilter.value = currentClassFilter;
    if (chartClassFilter) chartClassFilter.value = currentClassFilter;
    fetchSidebarStudents(currentTab);
  }

  /* ==========================================================
     INIT
     ========================================================== */
  function init() {
    bindEvents();
    initSidebarFilter();
    bindStudentSearch();

    /* dashboard-wide empty state for brand-new schools */
    if (DATA.totalStudents === 0 && DATA.totalResults === 0) {
      showDashboardEmpty();
      fetchSidebarStudents(currentTab);
      return;
    }

    /* init default chart (line is active by default) */
    initLineChart();

    /* load sidebar students on page load */
    fetchSidebarStudents(currentTab);
  }

  function getStarted() {
    if (DATA.uploadEnabled) {
      openUploadModal();
    } else {
      initPaystack();
    }
  }
  window.getStarted = getStarted;

  function uploadOrToast() {
    if (DATA.uploadEnabled) {
      openUploadModal();
    } else {
      showSubscriptionToast();
    }
  }
  window.uploadOrToast = uploadOrToast;

  function showDashboardEmpty() {
    if (!mainContent) return;

    if (DATA.uploadEnabled) {
      mainContent.innerHTML =
        '<div class="sd-dashboard-empty">' +
          '<div class="sd-dashboard-empty__icon">' +
            '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
              '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/>' +
              '<polyline points="14 2 14 8 20 8"/>' +
              '<line x1="16" y1="13" x2="8" y2="13"/>' +
              '<line x1="16" y1="17" x2="8" y2="17"/>' +
              '<polyline points="10 9 9 9 8 9"/>' +
            '</svg>' +
          '</div>' +
          '<h2 class="sd-dashboard-empty__title">Welcome to your dashboard</h2>' +
          '<p class="sd-dashboard-empty__desc">Upload your first batch of students to see insights, trends, and at-risk students here.</p>' +
          '<button class="sd-btn-solid" onclick="getStarted()">' +
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;margin-right:6px;"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>' +
            'Upload Students' +
          '</button>' +
        '</div>';
    } else {
      mainContent.innerHTML =
        '<div class="sd-dashboard-empty">' +
          '<div class="sd-dashboard-empty__icon sd-dashboard-empty__icon--gold">' +
            '<svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
              '<circle cx="12" cy="8" r="7"/>' +
              '<polyline points="8.21 13.89 7 23 12 20 17 23 15.79 13.88"/>' +
            '</svg>' +
          '</div>' +
          '<h2 class="sd-dashboard-empty__title">Welcome to your dashboard</h2>' +
          '<p class="sd-dashboard-empty__desc">Set up your school to start tracking student wellbeing.</p>' +
          '<button class="sd-btn-solid" onclick="getStarted()">' +
            'Get Started' +
            '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-left:6px;"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/></svg>' +
          '</button>' +
        '</div>';
    }
  }

  /* ── Mobile sidebar drawer ── */
  var hamburger = document.getElementById('sdHamburger');
  var sidebarOverlay = document.getElementById('sdSidebarOverlay');

  function openSidebar() {
    sidebar.classList.add('open');
    sidebarOverlay.classList.add('open');
    document.body.style.overflow = 'hidden';
  }
  function closeSidebar() {
    sidebar.classList.remove('open');
    sidebarOverlay.classList.remove('open');
    document.body.style.overflow = '';
  }

  if (hamburger) {
    hamburger.addEventListener('click', function() {
      if (sidebar.classList.contains('open')) closeSidebar();
      else openSidebar();
    });
  }
  var sidebarClose = document.getElementById('sdSidebarClose');
  if (sidebarClose) {
    sidebarClose.addEventListener('click', closeSidebar);
  }
  if (sidebarOverlay) {
    sidebarOverlay.addEventListener('click', closeSidebar);
  }
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closeSidebar();
  });

  /* run on DOM ready */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
