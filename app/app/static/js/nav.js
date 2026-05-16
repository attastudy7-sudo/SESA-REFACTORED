// app/static/js/nav.js - Desktop Side Nav Controller
// Handles toggle, indicator, dropdown, Turbo sync, a11y

(function() {
    'use strict';

    // Permanent listeners (once per session)
    if (!window._navListenersBound) {
        window._navListenersBound = true;

        // Turbo: Hide frame during render to prevent FOUC
        document.addEventListener('turbo:before-render', function(e) {
            const frame = e.detail.newBody.querySelector('turbo-frame#main-content');
            if (frame) frame.style.opacity = '0';
        });

        document.addEventListener('turbo:render', function() {
            const frame = document.getElementById('main-content');
            if (frame && frame.style.opacity === '0') {
                requestAnimationFrame(() => {
                    requestAnimationFrame(() => {
                        frame.style.transition = 'opacity 0.1s ease';
                        frame.style.opacity = '1';
                        setTimeout(() => {
                            frame.style.transition = '';
                            frame.style.opacity = '';
                        }, 120);
                    });
                });
            }
        });

        // Frame load: sync state, active links, stats
        document.addEventListener('turbo:frame-render', function(e) {
            if (e.target.id !== 'main-content') return;
            syncLayoutState(e.target);
            updateActiveLinks();
            if (typeof window.refreshUserStats === 'function') window.refreshUserStats();
            if (typeof window.moveDsnIndicator === 'function') {
                const active = document.querySelector('#dsnNav .dsn-link.active');
                window.moveDsnIndicator(active);
            }
        });

        document.addEventListener('turbo:frame-load', function(e) {
            window.knowlyTypesetMath?.(e.target);
        });
    }

    // Per-page init
    window.initNav = function() {
        const sideNav = document.getElementById('sideNav');
        const overlay = document.getElementById('sideNavOverlay');
        const mainContent = document.querySelector('turbo-frame#main-content, [data-shell-content]');
        if (!sideNav) return;

        // Indicator slide
        initIndicator();

        // Profile dropdown
        initProfileDropdown();

        // Toggle handlers
        initToggles(overlay, mainContent);

        // Keyboard nav
        initKeyboardNav();

        // Theme sync (if present)
        window.applyThemeResolution?.();
    };

    function syncLayoutState(frame) {
        const sideNav = document.getElementById('sideNav');
        const isExpanded = sideNav?.classList.contains('expanded');
        frame.classList.toggle('nav-expanded', isExpanded);
        document.body.classList.toggle('nav-is-expanded', isExpanded);
    }

    function initIndicator() {
        const nav = document.getElementById('dsnNav');
        const indicator = document.getElementById('dsnIndicator');
        if (!nav || !indicator) return;

        window.moveDsnIndicator = function(activeLink) {
            if (!activeLink) {
                indicator.style.opacity = '0';
                return;
            }
            const navRect = nav.getBoundingClientRect();
            const linkRect = activeLink.getBoundingClientRect();
            indicator.style.transition = 'top 0.25s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease';
            indicator.style.top = (linkRect.top - navRect.top + nav.scrollTop) + 'px';
            indicator.style.opacity = '1';
        };

        // Initial
        const active = nav.querySelector('.dsn-link.active');
        requestAnimationFrame(() => window.moveDsnIndicator(active));

        // Optimistic on click
        nav.querySelectorAll('.dsn-link').forEach(link => {
            link.addEventListener('click', () => {
                nav.querySelectorAll('.dsn-link').forEach(l => l.classList.remove('active'));
                link.classList.add('active');
                window.moveDsnIndicator(link);
            });
        });
    }

    function initProfileDropdown() {
        const trigger = document.getElementById('sideNavProfileTrigger');
        const dropdown = document.getElementById('sideNavProfileDropdown');
        const chevron = document.getElementById('sideNavProfileChevron');
        if (!trigger || !dropdown) return;

        const closeDropdown = () => {
            trigger.setAttribute('aria-expanded', 'false');
            dropdown.style.display = 'none';
            chevron.style.transform = 'rotate(0deg)';
        };

        const openDropdown = () => {
            const rect = trigger.getBoundingClientRect();
            const sideNavRect = document.getElementById('sideNav')?.getBoundingClientRect() || {left: 0};
            dropdown.style.position = 'fixed';
            dropdown.style.left = sideNavRect.left + 8 + 'px';
            dropdown.style.bottom = (window.innerHeight - rect.top + 8) + 'px';
            dropdown.style.top = 'auto';
            trigger.setAttribute('aria-expanded', 'true');
            dropdown.style.display = 'flex';
            dropdown.style.flexDirection = 'column';
            chevron.style.transform = 'rotate(180deg)';
            window.syncThemeButtons?.();
        };

        trigger.addEventListener('click', (e) => {
            if (window.innerWidth <= 1023) {
                window.openMobileSheet?.();
                return;
            }
            e.stopPropagation();
            trigger.getAttribute('aria-expanded') === 'true' ? closeDropdown() : openDropdown();
        });

        document.addEventListener('click', (e) => {
            if (!trigger.contains(e.target) && !dropdown.contains(e.target)) closeDropdown();
        });
    }

    function initToggles(overlay, mainContent) {
        const hamburger = document.getElementById('sideNavHamburger');
        const hamburgerCollapsed = document.getElementById('sideNavHamburgerCollapsed');
        const mobileHamburger = document.getElementById('mobileHamburgerBtn');

        const isMobile = () => window.innerWidth <= 1023;
        const closeMobile = () => {
            document.getElementById('sideNav')?.classList.remove('open');
            overlay?.classList.remove('open');
            document.body.classList.remove('modal-open', 'mobile-nav-active');
        };

        const toggleDesktop = () => {
            const sideNav = document.getElementById('sideNav');
            sideNav.classList.add('is-toggling');
            const isExpanded = sideNav.classList.toggle('expanded');
            mainContent?.classList.toggle('nav-expanded', isExpanded);
            document.body.classList.toggle('nav-is-expanded', isExpanded);
            localStorage.setItem('knowly-nav-expanded', isExpanded);
            setTimeout(() => sideNav.classList.remove('is-toggling'), 360);
        };

        [hamburger, hamburgerCollapsed, mobileHamburger].forEach(btn => {
            if (!btn) return;
            btn.addEventListener('click', () => {
                if (isMobile()) {
                    if (document.getElementById('sideNav')?.classList.contains('open')) closeMobile();
                    else {
                        document.getElementById('sideNav')?.classList.add('open');
                        overlay?.classList.add('open');
                        document.body.classList.add('modal-open', 'mobile-nav-active');
                    }
                } else {
                    toggleDesktop();
                }
            });
        });

        if (overlay) overlay.addEventListener('click', closeMobile);
        window.addEventListener('resize', () => { if (!isMobile()) closeMobile(); });

        // Restore state
        const saved = localStorage.getItem('knowly-nav-expanded') === 'true';
        if (!isMobile() && saved) {
            document.getElementById('sideNav')?.classList.add('expanded');
            syncLayoutState(mainContent);
        }
    }

    function initKeyboardNav() {
        const nav = document.getElementById('dsnNav');
        if (!nav) return;
        let focusedIndex = -1;
        const links = Array.from(nav.querySelectorAll('.dsn-link'));

        nav.addEventListener('keydown', (e) => {
            if (e.target.classList.contains('dsn-link')) {
                const idx = links.indexOf(e.target);
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    links[(idx + 1) % links.length].focus();
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    links[(idx - 1 + links.length) % links.length].focus();
                }
            }
        });
    }

    function updateActiveLinks() {
        const nav = document.getElementById('dsnNav');
        if (!nav) return;
        const path = window.location.pathname;
        nav.querySelectorAll('.dsn-link').forEach(link => {
            const href = link.getAttribute('href');
            const isActive = href === path || path.startsWith(href);
            link.classList.toggle('active', isActive);
        });
    }

    // Refresh user stats (XP)
    window.refreshUserStats = function() {
        const xpEl = document.querySelector('.dsn-user-meta');
        if (!xpEl) return;
        fetch('/api/user-stats')
            .then(r => r.json())
            .then(data => { if (data.xp !== undefined) xpEl.textContent = `${data.xp} XP`; })
            .catch(() => {});
    };

    // Theme management (reads auth state from <html data-is-authenticated>)
    window.setTheme = function(t) {
        localStorage.setItem('knowly-theme-mode', t);
        applyThemeResolution();
    };

    window.applyThemeResolution = function() {
        const htmlEl = document.documentElement;
        const isAuth = htmlEl.getAttribute('data-is-authenticated') === 'true';
        const stored = localStorage.getItem('knowly-theme-mode');
        const mode = stored || (isAuth ? 'system' : 'dark');
        let theme = mode;
        if (mode === 'system' || !['dark', 'light'].includes(mode)) {
            theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        if (htmlEl.getAttribute('data-theme') !== theme) {
            htmlEl.setAttribute('data-theme', theme);
        }
        if (htmlEl.getAttribute('data-user-preference') !== mode) {
            htmlEl.setAttribute('data-user-preference', mode);
        }
        if (typeof syncThemeButtons === 'function') syncThemeButtons();
        if (typeof syncDsnDarkIcon === 'function') syncDsnDarkIcon();
    };

    // Auto-init on load/Turbo
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', window.initNav);
    } else {
        window.initNav();
    }
    document.addEventListener('turbo:load', window.initNav);
})();

