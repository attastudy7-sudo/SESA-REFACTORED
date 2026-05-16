/**
 * global_search.js — KnowlySearch
 * Single source of truth for all YouTube/DB video search logic.
 *
 * Replaces inline <script> fetch/XHR blocks in:
 *   - templates/library/subject_videos.html  (DB-first + staggered reveal)
 *   - templates/library/video_browse.html    (Orb hero + sticky sync)
 *   - templates/partials/_video_browse_content.html  (legacy inline block)
 *   - templates/partials/_library_subject_videos_content.html  (legacy inline block)
 *
 * Exposes one global: window.KnowlySearch
 */

(function (global) {
  'use strict';

  /* ─────────────────────────────────────────────────────────────────────────
   * 1. CONSTANTS & THRESHOLDS
   * ──────────────────────────────────────────────────────────────────────── */
  var DB_SUPPLEMENT_THRESHOLD = 4;   // fetch external only when DB returns fewer than this
  var DEFAULT_LIMIT            = 30;
  var CSRF_META                = 'meta[name="csrf-token"]';

  /* ─────────────────────────────────────────────────────────────────────────
   * 2. CARD RENDERER
   *    Shared by DB results and external YouTube results.
   *    Accepts a unified VideoObject so callers never build HTML themselves.
   * ──────────────────────────────────────────────────────────────────────── */
  function buildCardHTML(v, isLoggedIn) {
    var thumb = v.thumbnail || ('https://img.youtube.com/vi/' + (v.youtube_id || v.video_id || '') + '/hqdefault.jpg');
    var href  = v.id
      ? ('/library/video/' + v.id)
      : (v.db_id
        ? ('/library/video/' + v.db_id)
        : ('/library/video/ext?yt=' + encodeURIComponent(v.youtube_id || v.video_id || '')
            + '&t=' + encodeURIComponent(v.title || '')
            + '&c=' + encodeURIComponent(v.channel || 'YouTube')));
    var label   = (v.subject || v.channel || '');
    var savedCls = v.is_saved ? 'saved' : '';
    var saveBtn  = isLoggedIn
      ? ('<button class="vb-save-btn ' + savedCls + '" data-video-id="' + (v.id || v.db_id || '') + '" data-youtube-id="' + (v.youtube_id || v.video_id || '') + '" data-title="' + _esc(v.title) + '" data-channel="' + _esc(v.channel || '') + '" data-thumbnail="' + _esc(thumb) + '" onclick="KnowlySearch.toggleVideoSave(event,this)" title="' + (v.is_saved ? 'Saved' : 'Save video') + '" style="position:absolute;bottom:12px;right:12px;z-index:5;"><i class="fas fa-bookmark"></i></button>')
      : '';

    return (
      '<div class="sv-card-container animate-row" style="position:relative;">' +
        '<a href="' + href + '" class="explore-card">' +
          '<div class="explore-thumb">' +
            '<img src="' + _esc(thumb) + '" alt="" class="explore-img" onerror="this.style.display=\'none\'">' +
            '<div class="explore-play"><svg viewBox="0 0 24 24" fill="white" width="22" height="22"><polygon points="6,3 21,12 6,21"/></svg></div>' +
          '</div>' +
          '<div class="explore-body">' +
            '<h3 class="explore-card-title">' + _esc(v.title || '') + '</h3>' +
            '<div class="explore-card-footer">' +
              '<p class="explore-card-meta">' + _esc(label) + '</p>' +
            '</div>' +
          '</div>' +
        '</a>' +
        saveBtn +
      '</div>'
    );
  }

  function _esc(str) {
    return String(str || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 3. EMPTY-STATE RENDERER  (task #4 — "No academic videos found" upgrade)
   * ──────────────────────────────────────────────────────────────────────── */
  function emptyHTML(query, isNonAcademic) {
    var msg = isNonAcademic
      ? ('No academic videos found for <strong>"' + _esc(query) + '"</strong>.<br>'
        + '<span style="font-size:0.85rem;opacity:0.8;">Try topics like "calculus", "physics", or "data structures" to find curated academic content.</span>')
      : ('No videos found for <strong>"' + _esc(query) + '"</strong>.<br>'
        + '<span style="font-size:0.85rem;opacity:0.8;">No academic videos matched — try a broader topic or check your spelling.</span>');
    return (
      '<div style="grid-column:1/-1;text-align:center;padding:3rem 1rem;color:var(--text-muted);">' +
        '<i class="fas fa-graduation-cap" style="font-size:2.5rem;margin-bottom:1rem;display:block;color:var(--primary);"></i>' +
        msg +
      '</div>'
    );
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 4. HYBRID SEARCH  (task #3 — DB-first, external supplemental)
   *
   *    opts = {
   *      resultsSection,   // element — shown during search
   *      resultsGrid,      // element — cards injected here
   *      originalContent,  // element — hidden during search
   *      filtersContainer, // element — category chips
   *      filtersWrap,      // element — wrapper for filters strip
   *      orbOuter,         // element|null — orb animation target
   *      onSearchStart,    // fn|null
   *      onClear,          // fn|null
   *    }
   * ──────────────────────────────────────────────────────────────────────── */
  function search(query, opts) {
    query = (query || '').trim();
    var rs  = opts.resultsSection;
    var rg  = opts.resultsGrid;
    var oc  = opts.originalContent;
    var fc  = opts.filtersContainer;
    var fw  = opts.filtersWrap;
    var isLoggedIn = !!(global.isLoggedIn);

    /* ── CLEAR ── */
    if (!query) {
      if (rs) rs.style.display  = 'none';
      if (oc) oc.style.display  = '';
      if (fc) fc.innerHTML = '';
      if (fw) fw.style.display  = 'none';
      if (opts.orbOuter) opts.orbOuter.classList.remove('searching');
      if (typeof opts.onClear === 'function') opts.onClear();
      return;
    }

    /* ── SHOW LOADING ── */
    if (oc) oc.style.display = 'none';
    if (rs) rs.style.display = 'block';
    if (rg) { rg.style.display = 'grid'; rg.innerHTML = _skeletonHTML(6); }
    if (fw) fw.style.display = 'none';
    if (opts.orbOuter) opts.orbOuter.classList.add('searching');
    if (typeof opts.onSearchStart === 'function') opts.onSearchStart(query);

    /* ── DB-FIRST SEARCH ── */
    var dbVideos = global.DB_VIDEOS || [];
    var qLower   = query.toLowerCase();
    var localMatches = dbVideos.filter(function(v) {
      return (v.title && v.title.toLowerCase().includes(qLower))
          || (v.subject && v.subject.toLowerCase().includes(qLower))
          || (v.academic_category && v.academic_category.toLowerCase().includes(qLower));
    });

    /* Render DB results immediately — instant feedback */
    if (localMatches.length >= DB_SUPPLEMENT_THRESHOLD) {
      _renderCards(rg, localMatches, query, isLoggedIn);
      _renderFilters(fc, fw, localMatches);
      if (opts.orbOuter) opts.orbOuter.classList.remove('searching');
      return; // DB was sufficient — no external call needed
    }

    /* ── SUPPLEMENTAL EXTERNAL FETCH ── */
    fetch('/library/search-videos?q=' + encodeURIComponent(query) + '&limit=' + DEFAULT_LIMIT)
      .then(function(res) { return res.json(); })
      .then(function(data) {
        if (data.error === 'non_academic') {
          if (rg) rg.innerHTML = emptyHTML(query, true);
          if (opts.orbOuter) opts.orbOuter.classList.remove('searching');
          return;
        }
        var external = (data.videos || []).map(function(v) {
          return {
            id:          v.db_id    || null,
            youtube_id:  v.video_id || v.youtube_id || '',
            title:       v.title    || '',
            thumbnail:   v.thumbnail || '',
            channel:     v.channel  || '',
            subject:     v.subject  || v.channel || '',
            is_saved:    false
          };
        });

        /* Merge: DB first (de-duped by youtube_id) then external extras */
        var seen     = {};
        var combined = [];
        localMatches.forEach(function(v) { seen[v.youtube_id] = true; combined.push(v); });
        external.forEach(function(v) {
          if (!seen[v.youtube_id]) { seen[v.youtube_id] = true; combined.push(v); }
        });

        if (!combined.length) {
          if (rg) rg.innerHTML = emptyHTML(query, false);
        } else {
          _renderCards(rg, combined, query, isLoggedIn);
          _renderFilters(fc, fw, combined);
        }
        if (opts.orbOuter) opts.orbOuter.classList.remove('searching');
      })
      .catch(function() {
        if (rg) rg.innerHTML = '<p style="grid-column:1/-1;color:var(--text-muted);padding:2rem;text-align:center;">Search failed — check your connection.</p>';
        if (opts.orbOuter) opts.orbOuter.classList.remove('searching');
      });
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 5. RENDER HELPERS
   * ──────────────────────────────────────────────────────────────────────── */
  function _renderCards(grid, videos, query, isLoggedIn) {
    if (!grid) return;
    grid.innerHTML = videos.map(function(v) { return buildCardHTML(v, isLoggedIn); }).join('');
    /* Staggered reveal via CSS + IntersectionObserver */
    _applyStaggeredReveal(grid);
  }

  function _renderFilters(container, wrap, videos) {
    if (!container) return;
    var cats = {};
    videos.forEach(function(v) { if (v.subject) cats[v.subject] = (cats[v.subject] || 0) + 1; });
    var keys = Object.keys(cats).sort(function(a, b) { return cats[b] - cats[a]; }).slice(0, 8);
    if (!keys.length) { if (wrap) wrap.style.display = 'none'; return; }
    container.innerHTML = keys.map(function(k) {
      return '<button class="vsn-filter-chip" onclick="KnowlySearch._filterByCategory(\'' + _esc(k) + '\')">' + _esc(k) + '</button>';
    }).join('');
    if (wrap) wrap.style.display = '';
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 6. STAGGERED ROW-BY-ROW ANIMATION  (task #5 — premium reveal)
   *
   *    Applied to .explore-grid children on initial load (initProgressiveReveal)
   *    AND to freshly-rendered search results (_applyStaggeredReveal).
   *    Uses IntersectionObserver so off-screen cards animate as they enter.
   * ──────────────────────────────────────────────────────────────────────── */
  function _applyStaggeredReveal(container) {
    if (!container) return;
    var cards = container.querySelectorAll('.sv-card-container, .animate-row');
    cards.forEach(function(card, i) {
      card.style.opacity   = '0';
      card.style.transform = 'translateY(14px)';
      card.style.transition = 'opacity 0.38s cubic-bezier(0.16,1,0.3,1), transform 0.38s cubic-bezier(0.16,1,0.3,1)';
      card.style.transitionDelay = Math.min(i * 0.05, 0.5) + 's';
    });

    if (!('IntersectionObserver' in window)) {
      /* Fallback — just reveal everything */
      cards.forEach(function(card) { _revealCard(card); });
      return;
    }

    var io = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (entry.isIntersecting) { _revealCard(entry.target); io.unobserve(entry.target); }
      });
    }, { rootMargin: '0px 0px -40px 0px', threshold: 0.05 });

    cards.forEach(function(card) { io.observe(card); });
  }

  function _revealCard(card) {
    card.style.opacity   = '1';
    card.style.transform = 'translateY(0)';
  }

  /* Public alias used by page init scripts */
  function initProgressiveReveal(gridId) {
    var grid = document.getElementById(gridId);
    if (grid) _applyStaggeredReveal(grid);
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 7. TOGGLE VIDEO SAVE  (task #3 — accepts DB_ID + external YouTube objects)
   *
   *    Replaces saveVideo(id) — now safe for both internal DB videos and
   *    external YouTube objects, preventing "undefined" errors.
   * ──────────────────────────────────────────────────────────────────────── */
  function toggleVideoSave(event, btn) {
    if (event) event.stopPropagation();
    if (!btn) return;

    /* Collect metadata from data attributes so external videos work too */
    var metadata = {
      video_id:   btn.dataset.videoId   || null,   // internal DB id
      youtube_id: btn.dataset.youtubeId || null,   // YT id for external
      title:      btn.dataset.title     || '',
      channel:    btn.dataset.channel   || '',
      thumbnail:  btn.dataset.thumbnail || ''
    };

    if (!metadata.video_id && !metadata.youtube_id) {
      console.warn('[KnowlySearch] toggleVideoSave: no video identifier on button', btn);
      return;
    }

    var isSaved = btn.classList.contains('saved');
    var method  = isSaved ? 'DELETE' : 'POST';
    var csrf    = (document.querySelector(CSRF_META) || {}).content || '';

    /* Optimistic UI */
    btn.classList.toggle('saved', !isSaved);
    btn.title = isSaved ? 'Save video' : 'Saved';

    fetch('/library/save-video', {
      method:  method,
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
      body:    JSON.stringify(metadata)
    })
    .then(function(res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
    })
    .catch(function() {
      /* Revert on failure */
      btn.classList.toggle('saved', isSaved);
      btn.title = isSaved ? 'Saved' : 'Save video';
    });
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 8. VOICE SEARCH
   * ──────────────────────────────────────────────────────────────────────── */
  function initVoice(opts) {
    /* opts = { inputId, micBtnId, stickyMicBtnId?, stickyInputId?, placeholder, onResult } */
    var SpeechRecognition = global.SpeechRecognition || global.webkitSpeechRecognition;
    var micBtn = document.getElementById(opts.micBtnId);
    var stickyMicBtn = opts.stickyMicBtnId ? document.getElementById(opts.stickyMicBtnId) : null;

    if (!SpeechRecognition) {
      if (micBtn) micBtn.style.display = 'none';
      if (stickyMicBtn) stickyMicBtn.style.display = 'none';
      return;
    }

    var recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = 'en-US';

    var active = false;

    function startVoice() {
      if (active) return;
      active = true;
      [micBtn, stickyMicBtn].forEach(function(b) { if (b) b.classList.add('active'); });
      var input = document.getElementById(opts.inputId);
      if (input) input.placeholder = 'Listening…';
      recognition.start();
    }

    recognition.onresult = function(e) {
      var q = e.results[0][0].transcript;
      var input = document.getElementById(opts.inputId);
      if (input) input.value = q;
      var stickyInput = opts.stickyInputId ? document.getElementById(opts.stickyInputId) : null;
      if (stickyInput) stickyInput.value = q;
      if (typeof opts.onResult === 'function') opts.onResult(q);
    };

    recognition.onend = function() {
      active = false;
      [micBtn, stickyMicBtn].forEach(function(b) { if (b) b.classList.remove('active'); });
      var input = document.getElementById(opts.inputId);
      if (input && !input.value) input.placeholder = opts.placeholder || 'Search…';
    };

    recognition.onerror = function() {
      active = false;
      [micBtn, stickyMicBtn].forEach(function(b) { if (b) b.classList.remove('active'); });
    };

    if (micBtn) micBtn.addEventListener('click', startVoice);
    if (stickyMicBtn) stickyMicBtn.addEventListener('click', startVoice);
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 9. IMAGE SEARCH
   * ──────────────────────────────────────────────────────────────────────── */
  function processImageSearch(fileInput, opts) {
    /* opts = { btnId, inputId, placeholder, onResult } */
    var file = fileInput.files && fileInput.files[0];
    if (!file) return;

    var btn  = document.getElementById(opts.btnId);
    var csrf = (document.querySelector(CSRF_META) || {}).content || '';

    if (btn) { btn.classList.add('active'); btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>'; }

    var fd = new FormData();
    fd.append('image', file);

    fetch('/library/image-search', { method: 'POST', headers: { 'X-CSRFToken': csrf }, body: fd })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var q = data.query || data.topic || '';
        var input = document.getElementById(opts.inputId);
        if (input && q) input.value = q;
        if (typeof opts.onResult === 'function') opts.onResult(q);
      })
      .catch(function() {
        console.warn('[KnowlySearch] image search failed');
      })
      .finally(function() {
        if (btn) { btn.classList.remove('active'); btn.innerHTML = '<i class="fas fa-image"></i>'; }
        fileInput.value = '';
      });
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 10. INFINITE SCROLL on original DB grid
   * ──────────────────────────────────────────────────────────────────────── */
  function initInfiniteScroll(opts) {
    /* opts = { gridId, originalContentId, initialSubject } */
    var page       = 1;
    var loading    = false;
    var exhausted  = false;
    var grid       = document.getElementById(opts.gridId);
    var container  = document.getElementById(opts.originalContentId);
    var subject    = opts.initialSubject || '';

    if (!grid) return;

    function loadMore() {
      if (loading || exhausted) return;
      loading = true;
      page++;
      var url = '/library/videos-page?page=' + page + (subject ? '&subject=' + encodeURIComponent(subject) : '');
      fetch(url)
        .then(function(r) { return r.json(); })
        .then(function(data) {
          if (!data.videos || !data.videos.length) { exhausted = true; return; }
          var frag = document.createElement('div');
          frag.innerHTML = data.videos.map(function(v) { return buildCardHTML(v, !!(global.isLoggedIn)); }).join('');
          while (frag.firstChild) grid.appendChild(frag.firstChild);
          _applyStaggeredReveal(grid);
        })
        .catch(function() {})
        .finally(function() { loading = false; });
    }

    window.addEventListener('scroll', function() {
      if (!container || container.style.display === 'none') return;
      var remaining = document.documentElement.scrollHeight - window.scrollY - window.innerHeight;
      if (remaining < 400) loadMore();
    }, { passive: true });
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 11. CATEGORY FILTER (chip click)
   * ──────────────────────────────────────────────────────────────────────── */
  function _filterByCategory(category) {
    var grid = document.getElementById('searchResultsGrid');
    if (!grid) return;
    grid.querySelectorAll('.sv-card-container').forEach(function(card) {
      var meta = card.querySelector('.explore-card-meta');
      var show = !category || (meta && meta.textContent.includes(category));
      card.style.display = show ? '' : 'none';
    });
    /* Highlight active chip */
    document.querySelectorAll('.vsn-filter-chip').forEach(function(chip) {
      chip.classList.toggle('active', chip.textContent === category);
    });
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 12. SKELETON LOADER  (6-card shimmer while fetch is in flight)
   * ──────────────────────────────────────────────────────────────────────── */
  function _skeletonHTML(n) {
    var card =
      '<div class="sk-card">' +
        '<div class="sk-thumb"></div>' +
        '<div class="sk-line sk-line--title"></div>' +
        '<div class="sk-line sk-line--meta"></div>' +
      '</div>';
    var out = '';
    for (var i = 0; i < n; i++) out += card;
    return out;
  }

  /* ─────────────────────────────────────────────────────────────────────────
   * 13. PUBLIC API
   * ──────────────────────────────────────────────────────────────────────── */
  global.KnowlySearch = {
    search:               search,
    toggleVideoSave:      toggleVideoSave,
    initVoice:            initVoice,
    processImageSearch:   processImageSearch,
    initProgressiveReveal: initProgressiveReveal,
    initInfiniteScroll:   initInfiniteScroll,
    _filterByCategory:    _filterByCategory   // used by rendered chip HTML
  };

})(window);
