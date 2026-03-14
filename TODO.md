# SESA Refactored - Task Tracker

## Current Task: Fix School Dashboard Empty States

### Step 1: Create this TODO.md [DONE]

### Step 2: Standardize empty states in app/templates/main/school_dashboard.html [DONE]
- [x] Stage Summary section: Replaced inline p → full .empty-state with icon/CTA
- [x] Recent Results: Added icon + CTA to existing .empty-state
- [x] Counsellors section: Added conditional empty state
- [x] Test on live server (http://127.0.0.1:5000)

### Step 3: Global CSS polish [DONE]
- [x] Updated .empty-state-icon opacity/color + .btn margin in main.css

### Step 4: Verify & Complete

**Server Running**: python main.py active. Test at http://127.0.0.1:5000/main.school_dashboard?school_id=1 (use DB with empty data if needed).
live