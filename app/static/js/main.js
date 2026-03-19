  /* ============================================================
    SESA — Main JavaScript
    ============================================================ */

  /* ─── Flash Toasts ───────────────────────────────────────── */
  (function initToasts() {
    const toasts = document.querySelectorAll('.flash-toast');
    toasts.forEach((toast, i) => {
      toast.addEventListener('click', () => dismissToast(toast));
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
  /*
    FIX 3: hamburger now exists in the DOM (added to base.html).
    getElementById('hamburger') will now find it on every page.
  */
  (function initDrawer() {
    const hamburger = document.getElementById('hamburger');
    const drawer    = document.getElementById('mobileDrawer');
    if (!hamburger || !drawer) return;

    function openDrawer() {
      drawer.classList.add('open');
      hamburger.classList.add('open');
      drawer.removeAttribute('aria-hidden');
      hamburger.setAttribute('aria-expanded', 'true');
      document.body.style.overflow = 'hidden';
    }
    function closeDrawer() {
      drawer.classList.remove('open');
      hamburger.classList.remove('open');
      drawer.setAttribute('aria-hidden', 'true');
      hamburger.setAttribute('aria-expanded', 'false');
      document.body.style.overflow = '';
    }
    function toggle() {
      drawer.classList.contains('open') ? closeDrawer() : openDrawer();
    }

    var justOpened = false;

    hamburger.addEventListener('click', function(e) {
      e.stopPropagation();
      e.preventDefault();
      justOpened = true;
      toggle();
      setTimeout(function() { justOpened = false; }, 50);
    });

    document.addEventListener('click', function(e) {
      if (justOpened) return;
      if (drawer.classList.contains('open') && !drawer.contains(e.target)) {
        closeDrawer();
      }
    });

    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape') closeDrawer();
    });

    drawer.querySelectorAll('a').forEach(function(link) {
      link.addEventListener('click', closeDrawer);
    });

    // Named close button inside the drawer header (both base.html and landing.html)
    var drawerCloseBtn = document.getElementById('drawerClose');
    if (drawerCloseBtn) {
      drawerCloseBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        closeDrawer();
      });
    }
  })();

  /* ─── Nav Scroll Blend ───────────────────────────────────── */
  /*
    FIX 1 + 2: Unified scroll handler for both navbars.
    - #mainNav  (base.html shared nav): always solid green; scroll just adds shadow.
    - #landingNav (landing.html dedicated nav): starts transparent, blends to
      solid on scroll, strips .transparent class so the transition is smooth.
    FIX 2: runs once on page load so the correct state is applied if the page
    was already scrolled when loaded (e.g. back-navigation, browser restore).
  */
  (function initNavScroll() {
    const nav = document.getElementById('landingNav') || document.getElementById('mainNav');
    if (!nav) return;

    var startsTransparent = nav.classList.contains('transparent');
    if (startsTransparent) nav.dataset.wasTransparent = 'true';

    // Landing page: use scroll position (no content boundary to observe)
    if (nav.id === 'landingNav') {
      function onScroll() {
        var isScrolled = window.scrollY > 40;
        nav.classList.toggle('scrolled', isScrolled);
        nav.classList.toggle('transparent', !isScrolled);
      }
      window.addEventListener('scroll', onScroll, { passive: true });
      onScroll();
      return;
    }

    // App pages: use IntersectionObserver on first content section
    // so the shadow fires exactly when content slides under the navbar
    var sentinel = document.querySelector('.stat-grid') ||
                   document.querySelector('.section') ||
                   document.querySelector('.card') ||
                   document.querySelector('.page-context');

    if (sentinel && 'IntersectionObserver' in window) {
      var observer = new IntersectionObserver(function(entries) {
        // When sentinel leaves the top of the viewport, content is under the nav
        nav.classList.toggle('scrolled', !entries[0].isIntersecting);
      }, { rootMargin: '-' + (parseInt(getComputedStyle(document.documentElement)
            .getPropertyValue('--navbar-height')) || 60) + 'px 0px 0px 0px' });
      observer.observe(sentinel);
      // Set correct initial state (e.g. back-navigation restores scroll position)
      nav.classList.toggle('scrolled', sentinel.getBoundingClientRect().top < 60);
    } else {
      // Fallback for browsers without IntersectionObserver
      function onScrollFallback() {
        nav.classList.toggle('scrolled', window.scrollY > 40);
      }
      window.addEventListener('scroll', onScrollFallback, { passive: true });
      onScrollFallback();
    }
  })();

  /* ─── Landing Page Drawer ─────────────────────────────────── */
  /* Landing page uses a separate #landingDrawer + #hamburger inside the landing-nav */
  (function initLandingDrawer() {
    // Only run on landing page (landingDrawer exists)
    var hamburger = document.getElementById('hamburger');
    var drawer    = document.getElementById('landingDrawer');
    if (!hamburger || !drawer) return;
    // If mobileDrawer already claimed the hamburger, skip (base.html pages)
    if (document.getElementById('mobileDrawer')) return;

    function open()  { drawer.classList.add('open');    hamburger.classList.add('open');    drawer.removeAttribute('aria-hidden'); hamburger.setAttribute('aria-expanded','true');  document.body.style.overflow='hidden'; }
    function close() { drawer.classList.remove('open'); hamburger.classList.remove('open'); drawer.setAttribute('aria-hidden','true'); hamburger.setAttribute('aria-expanded','false'); document.body.style.overflow=''; }

    var justOpened = false;
    hamburger.addEventListener('click', function(e) { e.stopPropagation(); e.preventDefault(); justOpened=true; drawer.classList.contains('open') ? close() : open(); setTimeout(function(){ justOpened=false; },50); });
    document.addEventListener('click', function(e) { if(justOpened) return; if(drawer.classList.contains('open') && !drawer.contains(e.target)) close(); });
    document.addEventListener('keydown', function(e) { if(e.key==='Escape') close(); });
    drawer.querySelectorAll('a').forEach(function(a){ a.addEventListener('click', close); });
    var closeBtn = document.getElementById('drawerClose');
    if (closeBtn) closeBtn.addEventListener('click', function(e){ e.stopPropagation(); close(); });
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
      const elapsed  = now - start;
      const progress = Math.min(elapsed / duration, 1);
      current = Math.round(progress * target);
      el.textContent = current;
      if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  })();

  /* ─── Student Search (school dashboard) ─────────────────── */
  (function initStudentSearch() {
    const input   = document.getElementById('studentSearch');
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
          const res  = await fetch(`/school/${schoolId}/search-students?query=${encodeURIComponent(q)}`);
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
      if (!input.contains(e.target)) results.hidden = true;
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

  /* ─── Crisis Help Button ─────────────────────────────────── */
  (function initCrisisBtn() {
    const btn   = document.getElementById('crisisBtn');
    const modal = document.getElementById('crisisModal');
    const close = document.getElementById('crisisModalClose');
    if (!btn || !modal) return;

    function openModal() {
      modal.style.display = 'flex';
      document.body.style.overflow = 'hidden';
      if (close) close.focus();
    }
    function closeModal() {
      modal.style.display = 'none';
      document.body.style.overflow = '';
      btn.focus();
    }

    btn.addEventListener('click', openModal);
    btn.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') openModal(); });
    if (close) close.addEventListener('click', closeModal);
    modal.addEventListener('click', e => { if (e.target === modal) closeModal(); });
    document.addEventListener('keydown', e => {
      if (e.key === 'Escape' && modal.style.display === 'flex') closeModal();
    });
  })(); 