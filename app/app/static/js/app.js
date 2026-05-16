function initPageReveal() {
    document.body.style.opacity = '1';
}
initPageReveal();
document.addEventListener('turbo:load', initPageReveal);


    
/* ── DARK MODE ── */
function updateDarkToggleUI(theme) {
    const isDark = theme === 'dark';
    const icon   = document.getElementById('darkToggleIcon');
    if (icon)  icon.className  = isDark ? 'fas fa-sun toggle-icon' : 'fas fa-moon toggle-icon';
    const mIcon  = document.getElementById('darkToggleIconMobile');
    const mPill  = document.getElementById('darkTogglePill');
    if (mIcon)  mIcon.className   = isDark ? 'fas fa-sun' : 'fas fa-moon';
    // Show the theme that will be activated when clicked
    if (mPill)  mPill.textContent  = isDark ? 'Light' : 'Dark';

    const sIcon  = document.getElementById('darkToggleIconSidebar');
    const sPill  = document.getElementById('darkTogglePillSidebar');
    if (sIcon)  sIcon.className   = isDark ? 'fas fa-sun' : 'fas fa-moon';
    if (sPill)  sPill.textContent  = isDark ? 'Light' : 'Dark';
}

function toggleDarkMode() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const next   = isDark ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('knowly-theme', next);
    updateDarkToggleUI(next);
}

/* ── SUGGESTIONS ── */
function closeSuggestions() {
    const el = document.getElementById('suggestionOverlay');
    if (el) el.style.display = 'none';
}
function switchSugTab(tab, btn) {
    document.querySelectorAll('.sug-list').forEach(function(el) { el.classList.add('hidden'); });
    document.querySelectorAll('.ob-tab').forEach(function(el) { el.classList.remove('active'); });
    document.getElementById('sug-' + tab).classList.remove('hidden');
    btn.classList.add('active');
}

/* ── PROFILE DROPDOWN (desktop only) ── */
function initProfileDropdown() {
    const trigger  = document.getElementById('profileTrigger');
    const dropdown = document.getElementById('profileDropdown');
    if (!trigger || !dropdown) return;

    if (trigger._profileDropdownBound) return;
    trigger._profileDropdownBound = true;

    trigger.addEventListener('click', function(e) {
        e.stopPropagation();
        const open = dropdown.classList.toggle('open');
        trigger.setAttribute('aria-expanded', String(open));
    });

    document.addEventListener('click', function() {
        if (dropdown.classList.contains('open')) {
            dropdown.classList.remove('open');
            trigger.setAttribute('aria-expanded', 'false');
        }
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && dropdown.classList.contains('open')) {
            dropdown.classList.remove('open');
            trigger.setAttribute('aria-expanded', 'false');
        }
    });
}
initProfileDropdown();
document.addEventListener('turbo:load', initProfileDropdown);

/* ── SCROLL SHADOW ── */

function initScrollShadow() {
    const nav = document.getElementById('topNav');
    if (nav) {
        if (nav._scrollBound) return;
        nav._scrollBound = true;
        window.addEventListener('scroll', function() {
            nav.classList.toggle('scrolled', window.scrollY > 8);
        }, { passive: true });
    }
}
initScrollShadow();
document.addEventListener('turbo:load', initScrollShadow);

/* ── FLASH AUTO-DISMISS ── */
function initFlashDismiss() {
    document.querySelectorAll('.flash').forEach(function(el) {
        if (el._dismissBound) return;
        el._dismissBound = true;
        setTimeout(function() {
            el.style.transition = 'opacity 0.4s, transform 0.4s';
            el.style.opacity    = '0';
            el.style.transform  = 'translateX(20px)';
            setTimeout(function() { el.remove(); }, 420);
        }, 5000);
    });
}
initFlashDismiss();
document.addEventListener('turbo:load', initFlashDismiss);

/* ── AUTOCOMPLETE (onboarding) ── */
function setupObDropdown(searchId, dropdownId, valueId, items) {
    const search   = document.getElementById(searchId);
    const dropdown = document.getElementById(dropdownId);
    const value    = document.getElementById(valueId);
    if (!search) return;

    search.addEventListener('input', function() {
        const q = this.value.toLowerCase();
        if (!this.value.trim()) {
            value.value = '';
            dropdown.classList.remove('open');
            dropdown.innerHTML = '';
            return;
        }
        value.value = this.value;
        const filtered = items.filter(function(i) { return i.toLowerCase().includes(q); });
        dropdown.innerHTML = '';
        if (filtered.length) {
            filtered.forEach(function(item) {
                const div = document.createElement('div');
                div.className = 'ob-dropdown-item';
                div.textContent = item;
                div.addEventListener('click', function() {
                    search.value = item;
                    value.value  = item;
                    dropdown.classList.remove('open');
                    dropdown.innerHTML = '';
                });
                dropdown.appendChild(div);
            });
            dropdown.classList.add('open');
        } else {
            dropdown.classList.remove('open');
        }
    });

    document.addEventListener('click', function(e) {
        if (!e.target.closest('#' + searchId) && !e.target.closest('#' + dropdownId))
            dropdown.classList.remove('open');
    });
}

updateDarkToggleUI(localStorage.getItem('knowly-theme') || 'light');

var GHANA_UNIVERSITIES = [
    "University of Ghana","KNUST","University of Cape Coast",
    "University for Development Studies","GIMPA","Ashesi University",
    "Central University","Valley View University","Methodist University Ghana",
    "UPSA","GCTU","Accra Technical University","Ho Technical University",
    "Kumasi Technical University","Takoradi Technical University",
    "Koforidua Technical University","Sunyani Technical University",
    "Cape Coast Technical University","Wa Technical University",
    "Bolgatanga Technical University","University of Health and Allied Sciences",
    "Ghana Institute of Journalism","NAFTI","Regent University College",
    "C.K. Tedam University","SD Dombo University","Other"
];
var GHANA_PROGRAMMES = [
    "BSc Computer Science","BSc Information Technology","BSc Computer Engineering",
    "BSc Electrical Engineering","BSc Mechanical Engineering","BSc Civil Engineering",
    "BSc Chemical Engineering","BA Economics","BSc Business Administration",
    "Bsc Packaging Technology",
    "BSc Accounting","BSc Marketing","BA English","BA History",
    "BSc Mathematics","BSc Statistics","BSc Physics","BSc Chemistry",
    "BSc Biology","BSc Biochemistry","BSc Nursing","BSc Pharmacy",
    "MBChB Medicine and Surgery","LLB Law","BSc Agriculture",
    "BSc Education","BA Communication Studies","BSc Psychology",
    "BSc Sociology","BSc Political Science","BSc Architecture",
    "BSc Quantity Surveying","BSc Land Economy","MBA",
    "MSc Computer Science","MSc Engineering","Other"
];

setupObDropdown('ob-school-search',    'ob-school-dropdown',    'ob-school-value',    GHANA_UNIVERSITIES);
setupObDropdown('ob-programme-search', 'ob-programme-dropdown', 'ob-programme-value', GHANA_PROGRAMMES);
(function () {
    const trigger = document.getElementById('mobileSheetTrigger');
    const sheet   = document.getElementById('mobileSheet');
    const overlay = document.getElementById('mobileSheetOverlay');
    if (!trigger || !sheet) return;

    function openSheet() {
        sheet.classList.add('open');
        overlay.classList.add('open');
        trigger.setAttribute('aria-expanded', 'true');
        document.body.style.overflow = 'hidden';
    }
    function closeSheet() {
        sheet.classList.remove('open');
        overlay.classList.remove('open');
        trigger.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
    }

    trigger.addEventListener('click', function(e) {
        e.stopPropagation();
        sheet.classList.contains('open') ? closeSheet() : openSheet();
    });
        sheet.querySelectorAll('a').forEach(function(a) {
        a.addEventListener('click', closeSheet);
    });
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeSheet();
    });
})();

/* ── NOTIFICATIONS ── */
function initNotifications() {
  // Collect desktop + mobile bell elements (mobile bell may not exist if logged out)
  const bells = [
    {
      toggle:   document.getElementById('notifToggle'),
      dropdown: document.getElementById('notifDropdown'),
      badge:    document.getElementById('notifBadge'),
      list:     document.getElementById('notifList'),
      markBtn:  document.getElementById('notifMarkRead'),
    },
    {
      toggle:   document.getElementById('notifToggleMobile'),
      dropdown: document.getElementById('notifDropdownMobile'),
      badge:    document.getElementById('notifBadgeMobile'),
      list:     document.getElementById('notifListMobile'),
      markBtn:  document.getElementById('notifMarkReadMobile'),
    },
  ].filter(b => b.toggle); // only keep entries where the element exists

  if (!bells.length) return;
  if (window._notifsInitialized) return;
  window._notifsInitialized = true;

  const ICONS = {
    like:          'fa-heart',
    comment:       'fa-comment',
    follow:        'fa-user-plus',
    post_approved: 'fa-check-circle',
    post_rejected: 'fa-times-circle',
  };

  function timeAgo(iso) {
    const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (diff < 60)    return 'just now';
    if (diff < 3600)  return Math.floor(diff / 60)   + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600)  + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  function notifHTML(notifs) {
    if (!notifs.length) {
      return '<div class="notif-empty"><i class="fas fa-bell-slash" style="font-size:1.5rem;margin-bottom:.5rem;display:block;"></i>No notifications yet</div>';
    }
    return notifs.map(n => `
      <a class="notif-item ${n.is_read ? '' : 'unread'}" href="${n.link || '#'}" data-id="${n.id}">
        <div class="notif-icon ${n.type || 'default'}">
          <i class="fas ${ICONS[n.type] || 'fa-bell'}"></i>
        </div>
        <div>
          <div class="notif-text">${n.message}</div>
          <div class="notif-time">${timeAgo(n.created_at)}</div>
        </div>
      </a>`).join('');
  }

  function updateBadge(count) {
    const label = count > 99 ? '99+' : String(count);
    const bottomBadge = document.getElementById('bottomNavBadge');
    bells.forEach(b => {
      if (!b.badge) return;
      if (count > 0) { b.badge.textContent = label; b.badge.classList.add('visible'); }
      else           { b.badge.classList.remove('visible'); }
    });
    if (bottomBadge) {
      if (count > 0) { bottomBadge.textContent = label; bottomBadge.classList.add('visible'); }
      else           { bottomBadge.classList.remove('visible'); }
    }
  }

  function closeAll(except) {
    bells.forEach(b => {
      if (b.dropdown === except) return;
      b.dropdown.classList.remove('open');
      if (b.toggle) b.toggle.setAttribute('aria-expanded', 'false');
    });
  }

  async function loadNotifs(listEl) {
    try {
      const r    = await fetch('/notifications');
      const data = await r.json();
      const html = notifHTML(data);
      // Render into all open lists simultaneously so both stay in sync
      bells.forEach(b => { if (b.list) b.list.innerHTML = html; });
      updateBadge(data.filter(n => !n.is_read).length);
    } catch(e) {
      if (listEl) listEl.innerHTML = '<div class="notif-empty">Could not load notifications.</div>';
    }
  }

  async function pollUnread() {
    try {
      const r    = await fetch('/notifications/unread-count');
      const data = await r.json();
      updateBadge(data.count);
    } catch(e) {}
  }

  // Wire each bell toggle
  bells.forEach(b => {
    b.toggle.addEventListener('click', function (e) {
      e.stopPropagation();
      closeAll(b.dropdown);
      const isOpen = b.dropdown.classList.toggle('open');
      b.toggle.setAttribute('aria-expanded', String(isOpen));
      if (isOpen) loadNotifs(b.list);
    });

    if (b.markBtn) {
      b.markBtn.addEventListener('click', async function (e) {
        e.stopPropagation();
        await fetch('/notifications/mark-read', {
          method: 'POST',
          headers: { 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]')?.content || '' }
        });
        updateBadge(0);
        bells.forEach(bell => {
          if (bell.list) bell.list.querySelectorAll('.notif-item.unread').forEach(el => el.classList.remove('unread'));
        });
      });
    }
  });

  // Bottom nav bell — opens the desktop dropdown repositioned above the bottom bar
  const bottomBell = document.getElementById('bottomNavNotif');
  if (bottomBell && bells[0]) {
    bottomBell.addEventListener('click', function (e) {
      e.stopPropagation();
      closeAll(bells[0].dropdown);
      const isOpen = bells[0].dropdown.classList.toggle('open');
      bells[0].toggle.setAttribute('aria-expanded', String(isOpen));
      if (isOpen) {
        loadNotifs(bells[0].list);
        bells[0].dropdown.style.cssText += ';bottom:4.5rem;top:auto;right:0.5rem;left:auto;';
      }
    });
  }

  // Close on outside click
  document.addEventListener('click', function (e) {
    bells.forEach(b => {
      if (!b.dropdown.contains(e.target) && e.target !== b.toggle) {
        b.dropdown.classList.remove('open');
        if (b.toggle) b.toggle.setAttribute('aria-expanded', 'false');
      }
    });
  });

  pollUnread();
  setInterval(pollUnread, 60000);
}
initNotifications();
document.addEventListener('turbo:load', initNotifications);

