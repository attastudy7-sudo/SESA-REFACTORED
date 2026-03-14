# TODO: Make Base Navigation Behave Like Landing Page

## Task Summary
Make the navigation in the base template (used across the app) change background color and show box-shadow on scroll, matching the behavior of the landing page navigation.

## Changes Needed:

### 1. CSS Updates (app/static/css/main.css)
- [x] Modify `.navbar` class to have transparent background initially (like landing-nav)
- [x] Modify `.navbar.scrolled` class to have solid green background and box-shadow when scrolled

### 2. Implementation
- The JavaScript in main.js already handles this via the `landingNav` ID
- Both landing.html and base.html use `id="landingNav"`, so the existing JS will work

## CSS Changes Detail:

### Current State:
```css
.navbar {
  background: transparent;
  color: #fff;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: 0 2px 12px rgba(0,0,0,.18);
  transition: background var(--transition), box-shadow var(--transition);
}

.navbar.scrolled {
  background: var(--green-800);
  box-shadow: var(--shadow-md);
}
```

### Target State:
```css
.navbar {
  background: transparent;
  color: #fff;
  position: sticky;
  top: 0;
  z-index: 100;
  box-shadow: none;
  transition: background var(--transition), box-shadow var(--transition);
}

.navbar.scrolled {
  background: var(--green-800);
  box-shadow: var(--shadow-md);
}
```

