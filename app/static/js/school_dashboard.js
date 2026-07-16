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
    claimCodesUrl:    node.dataset.claimCodesUrl
  };

  /* ---------- DOM refs ---------- */
  var sidebar          = $('#sdSidebar');
  var studentList      = $('#sdStudentList');
  var emptySidebar     = $('#sdEmptySidebar');
  var sidebarCount     = $('#sdSidebarCount');
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
  var activeGraph  = 'line';
  var currentStudentData = null;

  /* save the default mainContent HTML for restore */
  var savedMainHTML = mainContent ? mainContent.innerHTML : '';

  /* ---------- chart colours ---------- */
  var COLORS = {
    green:  '#4a7c59',
    gold:   '#c09526',
    teal:   '#2a7a7a',
    red:    '#d35400',
    muted:  '#95a5a6',
    bg:     '#f6f6f6',
    border: '#e8e8e8',
    white:  '#ffffff'
  };

  var STAGE_COLOURS = {
    'Normal':       '#22c55e',
    'Mild':         '#f59e0b',
    'Elevated':     '#f97316',
    'Clinical':     '#ef4444',
    'At Risk':      '#ef4444',
    'Unknown':      COLORS.muted
  };

  function stageColour(label) {
    var key = label.replace(/\s*Stage$/i, '');
    return STAGE_COLOURS[key] || COLORS.muted;
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

  /* --- donut --- */
  function initDonutChart() {
    var canvas = $('#dashDonut');
    if (!canvas) return;
    if (donutChart) { donutChart.destroy(); donutChart = null; }

    var labels = Object.keys(DATA.stage);
    var values = Object.values(DATA.stage);
    var colours = labels.map(function (l) { return stageColour(l); });

    if (labels.length === 0) {
      setChartEmpty(true);
      var legendEl = $('#sdDonutLegend');
      if (legendEl) legendEl.innerHTML = '';
      return;
    }
    setChartEmpty(false);

    donutChart = new Chart(canvas.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: labels,
        datasets: [{ data: values, backgroundColor: colours, borderWidth: 0 }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: '72%',
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var total = ctx.dataset.data.reduce(function (a, b) { return a + b; }, 0);
                var pct = total ? Math.round(ctx.raw / total * 100) : 0;
                return ctx.label + ': ' + ctx.raw + ' (' + pct + '%)';
              }
            }
          }
        }
      }
    });

    /* build custom legend */
    var legendEl = $('#sdDonutLegend');
    if (legendEl) {
      var total = values.reduce(function (a, b) { return a + b; }, 0);
      legendEl.innerHTML = labels.map(function (l, i) {
        var pct = total ? Math.round(values[i] / total * 100) : 0;
        return '<div class="sd-legend-item">' +
          '<span class="sd-legend-dot" style="background:' + colours[i] + ';"></span>' +
          '<span class="sd-legend-label">' + escHtml(l) + '</span>' +
          '<span class="sd-legend-value">' + values[i] + ' (' + pct + '%)</span></div>';
      }).join('');
    }
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

    /* colour segments: green where avg <= 30, red where avg > 30 */
    var segmentColours = values.map(function (v) { return v <= 30 ? COLORS.green : COLORS.red; });

    lineChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          borderColor: COLORS.green,
          backgroundColor: COLORS.green + '20',
          fill: true,
          tension: 0.3,
          pointBackgroundColor: segmentColours,
          pointRadius: 5,
          pointHoverRadius: 7
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: {
            beginAtZero: true,
            max: 100,
            grid: { color: COLORS.border },
            ticks: {
              font: { family: 'Manrope' },
              callback: function (v) { return v + '%'; }
            }
          },
          x: {
            grid: { display: false },
            ticks: { font: { family: 'Manrope' } }
          }
        }
      }
    });

    updateLineLegend(values);
  }

  function updateLineLegend(values) {
    var avgEl = $('#sdLineAvg');
    var monthsEl = $('#sdLineMonths');
    if (avgEl) {
      if (!values || values.length === 0) {
        avgEl.textContent = '—';
      } else {
        var avg = Math.round(values.reduce(function (a, b) { return a + b; }, 0) / values.length);
        avgEl.textContent = avg + '%';
      }
    }
    if (monthsEl) monthsEl.textContent = values ? values.length : 0;
  }

  /* --- compute status summary from monthly average values (lower % = better) --- */
  function computeStudentStatus(values) {
    if (!values || values.length === 0) {
      return { label: 'No Data', cls: '', trend: '', delta: 0, avg: 0, latest: 0 };
    }
    var avg = Math.round(values.reduce(function (a, b) { return a + b; }, 0) / values.length);
    var latest = values[values.length - 1];
    var delta = latest - avg;

    /* status from average */
    var label, cls;
    if (avg <= 20)      { label = 'Excellent'; cls = 'sd-badge--normal'; }
    else if (avg <= 40) { label = 'Good';      cls = 'sd-badge--normal'; }
    else if (avg <= 60) { label = 'Moderate';   cls = 'sd-badge--mild'; }
    else if (avg <= 80) { label = 'Needs Attention'; cls = 'sd-badge--elevated'; }
    else                { label = 'Critical';   cls = 'sd-badge--clinical'; }

    /* trend from latest vs average */
    var trend, arrow;
    if (delta < -3)      { trend = 'Improving'; arrow = '&#9660;'; }
    else if (delta > 3)  { trend = 'Worsening'; arrow = '&#9650;'; }
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
    var segmentColours = values.map(function (v) { return v <= 30 ? COLORS.green : COLORS.red; });

    progressChart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: {
        labels: labels,
        datasets: [{
          data: values,
          borderColor: COLORS.green,
          backgroundColor: COLORS.green + '20',
          fill: true,
          tension: 0.3,
          pointBackgroundColor: segmentColours,
          pointRadius: 5,
          pointHoverRadius: 7,
          borderWidth: 2
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
            grid: { color: COLORS.border },
            border: { display: false },
            ticks: {
              font: { family: 'Manrope', size: 12 },
              color: '#707070',
              callback: function (v) { return v + '%'; }
            }
          },
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: { font: { family: 'Manrope', size: 12 }, color: '#707070' }
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
    if (trendEl) trendEl.innerHTML = '<span class="sd-legend-summary__arrow">' + status.arrow + '</span> ' + status.trend + (status.delta ? ' (' + status.delta + '%)' : '');
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
      graphBtn.childNodes[graphBtn.childNodes.length - 1].textContent = ' ' + (GRAPH_LABELS[type] || 'Dashboard');
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

  function togglePeriodDropdown() {
    if (periodDropdown) periodDropdown.classList.toggle('open');
  }

  function closePeriodDropdown() {
    if (periodDropdown) periodDropdown.classList.remove('open');
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
      periodBtn.childNodes[periodBtn.childNodes.length - 1].textContent = ' ' + (PERIOD_LABELS[period] || 'All Time');
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
    if (targetBtn && targetBtn.dataset.locked) return;
    currentTab = tab;

    /* update nav link active states */
    $$('.sd-nav-link').forEach(function (btn) {
      btn.classList.toggle('sd-nav-link--active', btn.dataset.tab === tab);
    });

    /* fetch sidebar students */
    fetchSidebarStudents(tab);

    /* if at-risk tab, fetch fragment and swap mainContent */
    if (tab === 'at-risk') {
      fetchAtRiskFragment();
    } else {
      /* restore default panel */
      restoreDefaultPanel();
    }
  }

  function fetchSidebarStudents(tab) {
    if (!studentList) return;

    /* show loading */
    studentList.innerHTML = '<div class="sd-loading"><div class="sd-spinner"></div>Loading…</div>';

    var url = DATA.studentsUrl + '?tab=' + encodeURIComponent(tab);

    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      var students = data.students || [];
      if (sidebarCount) sidebarCount.textContent = data.total || students.length;

      if (students.length === 0) {
        studentList.innerHTML = '<div class="sd-student-list__empty"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#d1d5db" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="display:block;margin:0 auto 6px;"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>No students found</div>';
        return;
      }

      studentList.innerHTML = students.map(function (s) {
        var name = s.name || '';
        var initials = name.split(' ').map(function (w) { return w[0] || ''; }).join('').substring(0, 2).toUpperCase();
        var avatarColor = s.color || 'gray';
        return '<div class="sd-student-item" data-student-id="' + s.id + '">' +
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
    })
    .catch(function (err) {
      console.error('Sidebar fetch failed:', err);
      studentList.innerHTML = '<div class="sd-student-list__empty">Failed to load students</div>';
    });
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
        '<span style="flex:1;margin:0 8px;height:6px;background:#e8e8e8;border-radius:3px;overflow:hidden;">' +
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
        '<td><span class="sd-badge ' + stageClass + '">' + escHtml(r.stage || 'Unknown') + '</span></td>' +
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
            escHtml(s.class || '') +
            (s.gender && s.gender !== '—' ? ' · ' + escHtml(s.gender) : '') +
          '</div>' +
        '</div>' +
        '<div class="sd-chart-section sd-chart-section--student">' +
          '<div class="sd-chart-empty" id="sdStudentChartEmpty">' +
            '<svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#d1d5db" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="15" x2="21" y2="15"/><polyline points="8 12 11 9 14 12 17 7"/></svg>' +
            '<span>No chart data yet</span>' +
          '</div>' +
          '<div class="sd-chart-wrapper">' +
            '<div class="sd-chart-header">' +
              '<span class="sd-inner-title">Monthly Progress</span>' +
              '<span class="sd-progress-hint"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#999" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> Lower % is better</span>' +
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
            (stageRows || '<div style="color:#999;font-size:0.85rem;">No data</div>') +
          '</div>' +
          '<div class="sd-detail-section">' +
            '<div style="font-weight:700;font-size:0.85rem;margin-bottom:10px;">Assessment Coverage</div>' +
            (coverageRows || '<div style="color:#999;font-size:0.85rem;">No data</div>') +
          '</div>' +
        '</div>' +
        '<div style="margin-top:16px;">' +
          '<div style="font-weight:700;font-size:0.85rem;margin-bottom:10px;">Test History (' + (data.total_results || results.length) + ')</div>' +
          '<div class="sd-results-scroll">' +
            '<table class="sd-table"><thead><tr><th>Type</th><th>Score</th><th>Stage</th><th>Date</th></tr></thead>' +
            '<tbody>' + (resultRows || '<tr><td colspan="4" style="text-align:center;color:#999;">No results</td></tr>') + '</tbody></table>' +
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

    /* re-init active chart */
    if (activeGraph === 'donut') initDonutChart();
    if (activeGraph === 'bar') initBarChart();
    if (activeGraph === 'line') initLineChart();

    /* re-bind graph toggle */
    bindGraphToggle();

    /* init at-risk card links */
    initAtRiskCardLink();
  }

  /* ==========================================================
     AT-RISK FRAGMENT
     ========================================================== */
  function fetchAtRiskFragment() {
    mainContent.innerHTML = '<div class="sd-loading"><div class="sd-spinner"></div>Loading at-risk students…</div>';

    var url = '/school/' + DATA.schoolId + '/results?tab=at_risk&_fragment=1';

    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function (res) { return res.text(); })
    .then(function (html) {
      if (html && html.trim().length > 10) {
        mainContent.innerHTML = html;
        initAtRiskCardLink();
        bindAtRiskFilters();
      } else {
        mainContent.innerHTML = '<div class="sd-card sd-at-risk-empty">' +
          '<div class="sd-at-risk-empty__icon"><svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="#22c55e" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10z"/><path d="M8 12l3 3 5-5"/></svg></div>' +
          '<h3 class="sd-at-risk-empty__title">No students at risk</h3>' +
          '<p class="sd-at-risk-empty__desc">All students are currently at Normal or Mild stage. Keep monitoring by uploading new assessments regularly.</p>' +
        '</div>';
      }
    })
    .catch(function (err) {
      console.error('At-risk fetch failed:', err);
      mainContent.innerHTML = '<div class="sd-card" style="text-align:center;padding:48px;color:#999;">Failed to load at-risk data</div>';
    });
  }

  function bindAtRiskFilters() {
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
      card.style.cursor = 'pointer';
      card.onclick = function () {
        var tab = card.dataset.tab;
        if (tab) switchTab(tab);
      };
    });

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

      if (urlCode) urlCode.textContent = claimUrl;

      if (students.length === 0) {
        if (header) header.innerHTML = '';
        if (urlCode) urlCode.textContent = '';
        var copyRow = $('.sd-cc-copy-row');
        if (copyRow) copyRow.style.display = 'none';
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
      if (grid) grid.innerHTML = '<div class="sd-loading" style="color:#d35400;">Failed to load claim codes</div>';
    });
  }

  /* ==========================================================
     UPLOAD MODAL
     ========================================================== */
  function openUploadModal() {
    openOverlay('uploadModalOverlay');
  }

  function showSubscriptionToast() {
    var stack = document.querySelector('.flash-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'flash-stack';
      stack.setAttribute('role', 'status');
      stack.setAttribute('aria-live', 'polite');
      document.body.appendChild(stack);
    }
    var toast = document.createElement('div');
    toast.className = 'flash-toast warning';
    toast.setAttribute('role', 'alert');
    toast.innerHTML = '<span>Upload is available with an active subscription. Click <strong>Get Started</strong> to subscribe.</span>';
    stack.appendChild(toast);
    toast.addEventListener('click', function () {
      toast.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(40px)';
      setTimeout(function () { toast.remove(); }, 400);
    });
    setTimeout(function () {
      toast.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(40px)';
      setTimeout(function () { toast.remove(); }, 400);
    }, 5000);
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

    var uploadUrl = '/school/' + DATA.schoolId + '/upload';

    fetch(uploadUrl, {
      method: 'POST',
      body: formData,
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function (res) { return res.json(); })
    .then(function (data) {
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
      alert('Payment is not configured. Please contact support.');
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
            alert('Payment successful! Your subscription is now active.');
            location.reload();
          } else {
            alert('Payment verification failed. Please contact support.');
          }
        })
        .catch(function (err) {
          console.error('Verification failed:', err);
          alert('Payment could not be verified. Please contact support.');
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
    if (dd) dd.classList.toggle('open');
  }

  /* ==========================================================
     EVENT BINDING
     ========================================================== */

  function bindGraphToggle() {
    if (graphBtn && graphDropdown) {
      graphBtn.onclick = function (e) {
        e.stopPropagation();
        graphDropdown.classList.toggle('open');
      };
      $$('.sd-period-option', graphDropdown).forEach(function (opt) {
        opt.onclick = function () {
          switchGraph(opt.dataset.graph);
          graphDropdown.classList.remove('open');
        };
      });
    }
  }

  function bindEvents() {
    /* nav tabs */
    $$('.sd-nav-link').forEach(function (btn) {
      btn.onclick = function () { switchTab(btn.dataset.tab); };
    });

    /* graph toggle */
    bindGraphToggle();

    /* period dropdown — custom toggle */
    if (periodBtn) {
      periodBtn.onclick = function (e) {
        e.stopPropagation();
        togglePeriodDropdown();
      };
    }

    /* period option clicks */
    if (periodDropdown) {
      $$('.sd-period-option', periodDropdown).forEach(function (opt) {
        opt.onclick = function (e) {
          e.stopPropagation();
          selectPeriod(opt.dataset.period);
        };
      });
    }

    /* close period dropdown on outside click */
    document.addEventListener('click', function (e) {
      if (periodDropdown && periodDropdown.classList.contains('open')) {
        if (!periodDropdown.contains(e.target) && e.target !== periodBtn) {
          closePeriodDropdown();
        }
      }
      if (graphDropdown && graphDropdown.classList.contains('open')) {
        if (!graphDropdown.contains(e.target) && e.target !== graphBtn) {
          graphDropdown.classList.remove('open');
        }
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
    }

    /* close profile dropdown on outside click */
    document.addEventListener('click', function (e) {
      var dd = profileDropdown ? $('.sd-profile-dropdown', profileDropdown) : null;
      if (dd && dd.classList.contains('open')) {
        if (!profileDropdown.contains(e.target)) {
          dd.classList.remove('open');
        }
      }
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
      uploadZone.ondragover = function (e) { e.preventDefault(); uploadZone.style.borderColor = '#4a7c59'; };
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

    /* copy link */
    var copyBtn = $('#sdCopyLink');
    if (copyBtn) copyBtn.onclick = copyRegLink;

    /* paystack */
    var payBtn = $('#sdPayBtn');
    if (payBtn) payBtn.onclick = initPaystack;

    /* at-risk card */
    initAtRiskCardLink();
  }

  /* ==========================================================
     INIT
     ========================================================== */
  function init() {
    bindEvents();

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
