/* ═══════════════════════════════════════════════════════════════════════
   school_dashboard.js — Chart.js, AJAX, modal, payment, copy link
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
  'use strict';

  /* ── Data from server (set via data-* attributes) ──────────────────── */
  var root = document.getElementById('schoolDashboardData');
  if (!root) return;

  var stageData    = JSON.parse(root.dataset.stage   || '{}');
  var coverageData = JSON.parse(root.dataset.coverage || '{}');
  var totalStudents = parseInt(root.dataset.totalStudents || '0', 10);
  var schoolId     = root.dataset.schoolId || '';
  var paystackKey  = root.dataset.paystackKey || '';
  var email        = root.dataset.email || '';
  var amount       = parseInt(root.dataset.amount || '0', 10);
  var currency     = root.dataset.currency || 'GHS';
  var schoolName   = root.dataset.schoolName || '';
  var testMode     = root.dataset.testMode === 'true';
  var verifyUrl    = root.dataset.verifyUrl || '';

  var TEST_TYPES = [
    'Separation Anxiety Disorder',
    'Social Phobia',
    'Generalised Anxiety Disorder',
    'Panic Disorder',
    'Obsessive Compulsive Disorder',
    'Major Depressive Disorder'
  ];
  var TEST_SHORT = ['Sep. Anxiety', 'Social Phobia', 'Gen. Anxiety', 'Panic', 'OCD', 'Depression'];

  var STAGE_COLORS = {
    normal:   '#acf0dd',
    mild:     '#fecf44',
    elevated: '#ffdf90',
    moderate: '#ffdf90',
    clinical: '#f87171'
  };

  function stageColor(stage) {
    var s = stage.toLowerCase();
    for (var k in STAGE_COLORS) {
      if (s.indexOf(k) !== -1) return STAGE_COLORS[k];
    }
    return '#83a992';
  }

  /* ── 1. Stage Donut Chart ─────────────────────────────────────────── */
  var donutCtx = document.getElementById('stageDonutChart');
  if (donutCtx && Object.keys(stageData).length) {
    new Chart(donutCtx, {
      type: 'doughnut',
      data: {
        labels: Object.keys(stageData),
        datasets: [{
          data: Object.values(stageData),
          backgroundColor: Object.keys(stageData).map(stageColor),
          borderWidth: 2,
          borderColor: '#1a3a2a'
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        cutout: '68%',
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var total = ctx.dataset.data.reduce(function (a, b) { return a + b; }, 0);
                var pct = total > 0 ? Math.round(ctx.parsed / total * 100) : 0;
                return ' ' + ctx.label + ': ' + ctx.parsed + ' (' + pct + '%)';
              }
            }
          }
        }
      }
    });
  }

  /* ── 2. Coverage Bar Chart ────────────────────────────────────────── */
  var coverageCtx = document.getElementById('coverageBarChart');
  if (coverageCtx && totalStudents > 0) {
    var covValues = TEST_TYPES.map(function (t) { return coverageData[t] || 0; });
    var covPcts   = covValues.map(function (v) { return totalStudents > 0 ? Math.round(v / totalStudents * 100) : 0; });
    var covColors = covPcts.map(function (p) { return p >= 60 ? '#1a3a2a' : p >= 30 ? '#c9921a' : '#dc2626'; });

    new Chart(coverageCtx, {
      type: 'bar',
      data: {
        labels: TEST_SHORT,
        datasets: [{
          data: covPcts,
          backgroundColor: covColors,
          borderRadius: 4,
          borderSkipped: false
        }]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var idx = ctx.dataIndex;
                return ' ' + covValues[idx] + ' students (' + ctx.parsed.x + '%)';
              }
            }
          }
        },
        scales: {
          x: {
            min: 0, max: 100,
            ticks: { callback: function (v) { return v + '%'; }, font: { size: 11 } },
            grid: { color: 'rgba(0,0,0,0.05)' }
          },
          y: { ticks: { font: { size: 11 } }, grid: { display: false } }
        }
      }
    });
  }

  /* ── 3. Risk Breakdown Stacked Bar ────────────────────────────────── */
  var riskCtx = document.getElementById('riskBarChart');
  if (riskCtx && totalStudents > 0) {
    var tested    = TEST_TYPES.map(function (t) { return coverageData[t] || 0; });
    var notTested = tested.map(function (v) { return Math.max(0, totalStudents - v); });

    new Chart(riskCtx, {
      type: 'bar',
      data: {
        labels: TEST_SHORT,
        datasets: [
          { label: 'Tested', data: tested, backgroundColor: '#1a3a2a', borderRadius: 4, borderSkipped: false },
          { label: 'Not Tested', data: notTested, backgroundColor: '#e5e7eb', borderRadius: 4, borderSkipped: false }
        ]
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: true, position: 'bottom', labels: { font: { size: 11 }, boxWidth: 12 } },
          tooltip: {
            callbacks: {
              label: function (ctx) { return ' ' + ctx.dataset.label + ': ' + ctx.parsed.x + ' students'; }
            }
          }
        },
        scales: {
          x: { stacked: true, ticks: { font: { size: 11 } }, grid: { color: 'rgba(0,0,0,0.05)' } },
          y: { stacked: true, ticks: { font: { size: 11 } }, grid: { display: false } }
        }
      }
    });
  }

  /* ── 4. Period Tab AJAX ───────────────────────────────────────────── */
  var periodTabs = document.getElementById('periodTabs');
  if (periodTabs) {
    periodTabs.addEventListener('click', function (e) {
      var a = e.target.closest('a[data-period]');
      if (!a) return;
      e.preventDefault();

      var period = a.dataset.period;
      setActiveTab(period);

      fetch(a.href, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          /* Coverage chart */
          var covChart = Chart.getChart('coverageBarChart');
          if (covChart && data.coverage_counts) {
            var newCovValues = TEST_TYPES.map(function (t) { return data.coverage_counts[t] || 0; });
            var newCovPcts   = newCovValues.map(function (v) {
              return totalStudents > 0 ? Math.round(v / totalStudents * 100) : 0;
            });
            covChart.data.datasets[0].data = newCovPcts;
            covChart.data.datasets[0].backgroundColor = newCovPcts.map(function (p) {
              return p >= 60 ? '#1a3a2a' : p >= 30 ? '#c9921a' : '#dc2626';
            });
            covChart.update();
          }

          /* Donut chart */
          var donutChart = Chart.getChart('stageDonutChart');
          if (donutChart && data.stage_counts) {
            donutChart.data.labels = Object.keys(data.stage_counts);
            donutChart.data.datasets[0].data = Object.values(data.stage_counts);
            donutChart.data.datasets[0].backgroundColor = Object.keys(data.stage_counts).map(stageColor);
            donutChart.update();
          }

          /* Update stat card label */
          var allLabels = document.querySelectorAll('.dash-stat__label');
          allLabels.forEach(function (el) {
            if (el.textContent.indexOf('Tests') !== -1) {
              var total = Object.values(data.stage_counts).reduce(function (a, b) { return a + b; }, 0);
              el.previousElementSibling.textContent = total;
              el.textContent = 'Tests (' + period.charAt(0).toUpperCase() + period.slice(1) + ')';
            }
          });

          /* Update legend */
          var legend = document.getElementById('stageLegend');
          if (legend && data.stage_counts) {
            var total = Object.values(data.stage_counts).reduce(function (a, b) { return a + b; }, 0);
            var html = '';
            Object.entries(data.stage_counts).forEach(function (e) {
              var stage = e[0], count = e[1];
              var color = stageColor(stage);
              var pct = total > 0 ? Math.round(count / total * 1000) / 10 : 0;
              html += '<div class="dash-legend-item">';
              html += '<span class="dash-legend-dot" style="background:' + color + ';"></span>';
              html += '<span class="dash-legend-label">' + stage + '</span>';
              html += '<strong class="dash-legend-val">' + pct + '%</strong>';
              html += '</div>';
            });
            legend.innerHTML = html;
          }

          /* Update subtitle */
          var subEl = document.getElementById('coverageSub');
          if (subEl) subEl.textContent = 'Per student, this ' + period;

          history.replaceState(null, '', a.href);
        })
        .catch(function () { window.location.href = a.href; });
    });
  }

  function setActiveTab(period) {
    document.querySelectorAll('#periodTabs a').forEach(function (a) {
      if (a.dataset.period === period) {
        a.className = 'dash-period-tab dash-period-tab--active';
      } else {
        a.className = 'dash-period-tab dash-period-tab--inactive';
      }
    });
  }

  /* ── 5. Upload Modal ──────────────────────────────────────────────── */
  var uploadModal   = document.getElementById('uploadModal');
  var openUploadBtn = document.getElementById('openUploadBtn');
  var openUploadBtnRight = document.getElementById('openUploadBtnRight');
  var closeUploadBtn = document.getElementById('closeUploadBtn');

  function openModal() {
    if (!uploadModal) return;
    uploadModal.style.display = 'flex';
    requestAnimationFrame(function () { uploadModal.classList.add('open'); });
  }
  if (openUploadBtn && uploadModal) openUploadBtn.addEventListener('click', openModal);
  if (openUploadBtnRight && uploadModal) openUploadBtnRight.addEventListener('click', openModal);

  function closeModal() {
    if (!uploadModal) return;
    uploadModal.classList.remove('open');
    setTimeout(function () { uploadModal.style.display = 'none'; }, 300);
  }

  if (closeUploadBtn) closeUploadBtn.addEventListener('click', closeModal);
  if (uploadModal) {
    uploadModal.addEventListener('click', function (e) {
      if (e.target === uploadModal) closeModal();
    });
  }

  /* ── 6. Upload Zone — file select + drag & drop ───────────────────── */
  var uploadZone = document.getElementById('uploadZone');
  var fileInput  = document.getElementById('fileInput');

  if (uploadZone && fileInput) {
    uploadZone.addEventListener('click', function () { fileInput.click(); });

    fileInput.addEventListener('change', function () {
      if (this.files && this.files[0]) {
        var icon = uploadZone.querySelector('.dash-upload-zone__icon');
        var title = uploadZone.querySelector('.dash-upload-zone__title');
        var sub   = uploadZone.querySelector('.dash-upload-zone__sub');
        if (icon) icon.className = 'dash-upload-zone__icon fa-solid fa-check';
        if (title) title.textContent = this.files[0].name;
        if (sub) sub.textContent = 'Ready to upload';
        uploadZone.classList.add('has-file');
      }
    });

    uploadZone.addEventListener('dragover', function (e) {
      e.preventDefault();
      this.classList.add('dragover');
    });
    uploadZone.addEventListener('dragleave', function () {
      this.classList.remove('dragover');
    });
    uploadZone.addEventListener('drop', function (e) {
      e.preventDefault();
      this.classList.remove('dragover');
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        fileInput.files = e.dataTransfer.files;
        fileInput.dispatchEvent(new Event('change'));
      }
    });
  }

  /* ── 7. Copy Link ─────────────────────────────────────────────────── */
  var copyBtn = document.getElementById('copyLinkBtn');
  if (copyBtn) {
    copyBtn.addEventListener('click', function () {
      var link = copyBtn.dataset.link;
      if (!link) return;
      navigator.clipboard.writeText(link).then(function () {
        var label = document.getElementById('copyLinkLabel');
        if (label) {
          label.textContent = 'Copied!';
          setTimeout(function () { label.textContent = 'Copy'; }, 2000);
        }
      });
    });
  }

  /* ── 8. Guide Banner Dismiss ──────────────────────────────────────── */
  var guideBanner = document.getElementById('guideBanner');
  if (guideBanner) {
    var dismissBtn = guideBanner.querySelector('[data-dismiss]');
    if (dismissBtn) {
      dismissBtn.addEventListener('click', function () { guideBanner.style.display = 'none'; });
    }
  }

  /* ── 9. Paystack Payment ──────────────────────────────────────────── */
  window.initiatePayment = function () {
    var btn = document.getElementById('paystackBtn');
    if (!btn || typeof PaystackPop === 'undefined') return;
    btn.disabled = true;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Loading…';

    var handler = PaystackPop.setup({
      key: paystackKey,
      email: email,
      amount: amount,
      currency: currency,
      ref: 'SESA-' + Math.floor(Math.random() * 1000000000),
      label: schoolName + ' — SESA Subscription',
      metadata: { school_id: schoolId, school_name: schoolName, test_mode: testMode },
      callback: function (response) {
        window.location.href = verifyUrl + '?reference=' + response.reference;
      },
      onClose: function () {
        btn.disabled = false;
        btn.innerHTML = '<i class="fa-solid fa-credit-card"></i> Pay to Activate Subscription';
      }
    });
    handler.openIframe();
  };

})();
