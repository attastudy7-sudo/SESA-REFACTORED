/* ============================================================
   SESA — Main JavaScript
   ============================================================ */

/* ─── Flash Toasts ───────────────────────────────────────── */
(function initToasts() {
  const toasts = document.querySelectorAll('.flash-toast');
  toasts.forEach((toast, i) => {
    // Dismiss on click
    toast.addEventListener('click', () => dismissToast(toast));
    // Auto-dismiss after 4.5s
    setTimeout(() => dismissToast(toast), 4500 + i * 300);
  });

  function dismissToast(el) {
    el.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
    el.style.opacity = '0';
    el.style.transform = 'translateX(40px)';
    setTimeout(() => el.remove(), 400);
  }
})();

/* ─── Hamburger / Mobile Drawer ──────────────────────────── */
(function initDrawer() {
  const hamburger = document.getElementById('hamburger');
  const drawer = document.getElementById('mobileDrawer');
  const overlay = document.getElementById('drawerOverlay');
  const closeBtn = document.getElementById('drawerClose');
  if (!hamburger || !drawer) return;

  function openDrawer() { drawer.classList.add('open'); overlay.classList.add('open'); document.body.style.overflow = 'hidden'; }
  function closeDrawer() { drawer.classList.remove('open'); overlay.classList.remove('open'); document.body.style.overflow = ''; }

  hamburger.addEventListener('click', openDrawer);
  closeBtn?.addEventListener('click', closeDrawer);
  overlay?.addEventListener('click', closeDrawer);
})();

/* ─── Landing Nav Scroll ─────────────────────────────────── */
(function initLandingNav() {
  const nav = document.getElementById('landingNav');
  if (!nav) return;
  window.addEventListener('scroll', () => {
    nav.classList.toggle('scrolled', window.scrollY > 40);
  }, { passive: true });
})();

/* ─── Admin Tabs ─────────────────────────────────────────── */
(function initAdminTabs() {
  const tabs = document.querySelectorAll('.admin-tab');
  if (!tabs.length) return;

  function activateTab(id) {
    tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === id));
    document.querySelectorAll('.admin-tab-panel').forEach(p => {
      p.classList.toggle('active', p.id === id);
    });
    history.replaceState(null, '', '#' + id);
  }

  tabs.forEach(tab => tab.addEventListener('click', () => activateTab(tab.dataset.tab)));

  // Activate from URL hash
  const hash = location.hash.slice(1);
  const defaultTab = hash && document.getElementById(hash) ? hash : tabs[0]?.dataset.tab;
  if (defaultTab) activateTab(defaultTab);
})();

/* ─── Quiz Options ───────────────────────────────────────── */
(function initQuizOptions() {
  document.querySelectorAll('.quiz-option').forEach(opt => {
    opt.addEventListener('click', () => {
      const input = opt.querySelector('input[type=radio]');
      if (input) {
        input.checked = true;
        document.querySelectorAll('.quiz-option').forEach(o => o.classList.remove('selected'));
        opt.classList.add('selected');
      }
    });
  });
})();

/* ─── Confirm Delete ─────────────────────────────────────── */
(function initDeleteConfirm() {
  document.querySelectorAll('.confirm-delete').forEach(form => {
    form.addEventListener('submit', e => {
      const item = form.dataset.item || 'this item';
      if (!confirm(`Are you sure you want to delete ${item}? This cannot be undone.`)) {
        e.preventDefault();
      }
    });
  });
})();

/* ─── Score Countdown Animation ─────────────────────────── */
(function initScoreCounter() {
  const el = document.getElementById('scoreCounter');
  if (!el) return;
  const target = parseInt(el.dataset.target, 10) || 0;
  let current = 0;
  const duration = 800;
  const start = performance.now();

  function step(now) {
    const elapsed = now - start;
    const progress = Math.min(elapsed / duration, 1);
    current = Math.round(progress * target);
    el.textContent = current;
    if (progress < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
})();

/* ─── Student Search (school dashboard) ─────────────────── */
(function initStudentSearch() {
  const input = document.getElementById('studentSearch');
  const results = document.getElementById('searchResults');
  if (!input || !results) return;

  const schoolId = input.dataset.schoolId;
  let debounce;

  input.addEventListener('input', () => {
    clearTimeout(debounce);
    const q = input.value.trim();
    if (!q) { results.innerHTML = ''; results.hidden = true; return; }
    debounce = setTimeout(async () => {
      try {
        const res = await fetch(`/school/${schoolId}/search-students?query=${encodeURIComponent(q)}`);
        const data = await res.json();
        if (!data.length) {
          results.innerHTML = '<li class="search-empty">No students found</li>';
        } else {
          results.innerHTML = data.map(s =>
            `<li><strong>${s.fname} ${s.lname}</strong> <span>@${s.username}</span></li>`
          ).join('');
        }
        results.hidden = false;
      } catch (err) {
        console.error(err);
      }
    }, 300);
  });

  document.addEventListener('click', e => {
    if (!input.contains(e.target)) { results.hidden = true; }
  });
})();

/* ─── Upload File Name Display ───────────────────────────── */
(function initFileInput() {
  document.querySelectorAll('.file-upload-input').forEach(input => {
    input.addEventListener('change', () => {
      const label = input.closest('.file-upload-area')?.querySelector('.file-name');
      if (label) label.textContent = input.files[0]?.name || 'No file chosen';
    });
  });
})();
