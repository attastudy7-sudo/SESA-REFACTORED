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
    'Normal':       COLORS.green,
    'Mild':         COLORS.gold,
    'Elevated':     '#e67e22',
    'Clinical':     COLORS.red,
    'At Risk':      COLORS.red,
    'Unknown':      COLORS.muted
  };

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
    var colours = labels.map(function (l) { return STAGE_COLOURS[l] || COLORS.muted; });

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
        cutout: '65%',
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
            reverse: true,
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

  /* --- student progress chart (reversed Y — monthlyData from student detail IS [{month,label,average}]) --- */
  function initProgressChart(monthlyData) {
    var canvas = $('#sdProgressCanvas');
    if (!canvas) return;
    if (progressChart) { progressChart.destroy(); progressChart = null; }

    if (!monthlyData || monthlyData.length === 0) {
      progressChart = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { labels: [], datasets: [] },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: { enabled: false } }
        }
      });
      return;
    }

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
          pointHoverRadius: 7
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          y: {
            reverse: true,
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
    studentList.innerHTML = '<div class="sd-student-list__empty"><div class="sd-spinner"></div>Loading…</div>';

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
        var stageText = s.stage || 'Unknown';
        var stageClass = 'sd-badge--' + (stageText || 'unknown').toLowerCase().replace(' stage', '').replace(/\s+/g, '-');
        var avatarColor = s.color || 'gray';
        return '<div class="sd-student-item" data-student-id="' + s.id + '">' +
          '<div class="sd-student-item__avatar sd-student-item__avatar--' + avatarColor + '">' + escHtml(initials) + '</div>' +
          '<div class="sd-student-item__info">' +
            '<div class="sd-student-item__name">' + escHtml(name) + '</div>' +
            '<div class="sd-student-item__meta">' +
              '<span class="sd-badge ' + stageClass + '">' + escHtml(stageText) + '</span>' +
              (s.class ? '<span style="margin-left:6px;font-size:0.75rem;color:#999;">' + escHtml(s.class) + '</span>' : '') +
            '</div>' +
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
          '<span style="display:block;height:100%;width:' + pct + '%;background:' + (STAGE_COLOURS[key] || COLORS.muted) + ';border-radius:3px;"></span>' +
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
          (latestStage ? ' <span style="font-weight:400;font-size:0.75rem;color:#999;">(' + escHtml(latestStage) + ')</span>' : '') +
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
          '<div class="sd-progress-hint"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#999" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/></svg> Monthly progress — lower % is better</div>' +
          '<div class="sd-chart-wrapper" style="height:220px;">' +
            '<canvas id="sdProgressCanvas"></canvas>' +
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
    mainContent.innerHTML = '<div style="text-align:center;padding:48px;color:#999;"><div class="sd-spinner"></div>Loading at-risk students…</div>';

    var url = '/school/' + DATA.schoolId + '?tab=at_risk&_fragment=1';

    fetch(url, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function (res) { return res.text(); })
    .then(function (html) {
      if (html && html.trim().length > 10) {
        mainContent.innerHTML = html;
        initAtRiskCardLink();
      } else {
        mainContent.innerHTML = '<div class="sd-card" style="text-align:center;padding:48px;color:#999;">No at-risk students found <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#999" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:middle;"><path d="M22 11.08V12a10 10 0 11-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg></div>';
      }
    })
    .catch(function (err) {
      console.error('At-risk fetch failed:', err);
      mainContent.innerHTML = '<div class="sd-card" style="text-align:center;padding:48px;color:#999;">Failed to load at-risk data</div>';
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
    var riskBanner = $('#sdRiskBanner');
    if (riskBanner) {
      riskBanner.style.cursor = 'pointer';
      riskBanner.onclick = function () { switchTab('at-risk'); };
    }
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
    openOverlay('sdClaimModalOverlay');
    if (grid) grid.innerHTML = '<div style="text-align:center;padding:24px;color:#999;">Loading claim codes…</div>';

    fetch(DATA.claimCodesUrl, {
      headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(function (res) { return res.json(); })
    .then(function (data) {
      var students = data.students || [];
      if (students.length === 0) {
        if (grid) grid.innerHTML = '<div style="text-align:center;padding:24px;color:#999;">No unclaimed codes</div>';
        return;
      }
      if (grid) {
        grid.innerHTML = students.map(function (s) {
          /* route returns flat "name" field */
          var code = s.claim_code || '——';
          var name = s.name || 'Unnamed';
          return '<div class="sd-cc-slip">' +
            '<div class="sd-cc-slip__header">' +
              '<div class="sd-cc-slip__label">Student</div>' +
              '<div class="sd-cc-slip__name">' + escHtml(name) + '</div>' +
              '<div class="sd-cc-slip__meta">' + escHtml(s.class_group || '') + '</div>' +
            '</div>' +
            '<div class="sd-cc-slip__divider"></div>' +
            '<div class="sd-cc-slip__code-label">Claim Code</div>' +
            '<div class="sd-cc-slip__code">' + escHtml(code) + '</div>' +
            '<div class="sd-cc-slip__url">' + escHtml(data.claim_url || '') + '</div>' +
          '</div>';
        }).join('');
      }
    })
    .catch(function (err) {
      console.error('Claim codes fetch failed:', err);
      if (grid) grid.innerHTML = '<div style="text-align:center;padding:24px;color:#d35400;">Failed to load claim codes</div>';
    });
  }

  /* ==========================================================
     UPLOAD MODAL
     ========================================================== */
  function openUploadModal() {
    openOverlay('uploadModalOverlay');
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
    var bannerUploadBtn = $('#bannerUploadBtn');
    if (uploadBtn) uploadBtn.onclick = openUploadModal;
    if (bannerUploadBtn) bannerUploadBtn.onclick = openUploadModal;

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

    /* at-risk card + banner */
    initAtRiskCardLink();
  }

  /* ==========================================================
     INIT
     ========================================================== */
  function init() {
    bindEvents();

    /* init default chart (line is active by default) */
    initLineChart();

    /* load sidebar students on page load */
    fetchSidebarStudents(currentTab);
  }

  /* run on DOM ready */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
