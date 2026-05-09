# React + Babel guidelines for interactive widgets

When building interactive prototypes or widgets that benefit from React
state management, follow these rules. For physics simulations or
particle systems, prefer **vanilla + Canvas** — React adds unnecessary
overhead.

## CDN scripts (pinned versions with integrity hashes)

Use these exact script tags — do **NOT** use unpinned versions:

```html
<script src="https://unpkg.com/react@18.3.1/umd/react.development.js"
        integrity="sha384-hD6/rw4ppMLGNu3tX5cjIb+uRZ7UkRJ6BPkLpg4hAu/6onKUg4lLsHAs9EBPT82L"
        crossorigin="anonymous"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.development.js"
        integrity="sha384-u6aeetuaXnQ38mYT8rp6sbXaQe3NL9t+IBXmnYxwkUI2Hw4bsp2Wvmx4yRQF1uAm"
        crossorigin="anonymous"></script>
<script src="https://unpkg.com/@babel/standalone@7.29.0/babel.min.js"
        integrity="sha384-m08KidiNqLdpJqLq95G/LEi8Qvjl/xUYll3QILypMoQ65QorJ9Lvtp2RXYGBFj1y"
        crossorigin="anonymous"></script>
```

## Rules

1. Use `<script type="text/babel">` for JSX code.
2. Mount to `<div id="root"></div>`.
3. **CRITICAL**: give global-scoped style objects SPECIFIC names. NEVER
   write `const styles = {}`. Use `const quizStyles = {}`,
   `const dashboardStyles = {}`, etc. — global collisions between
   script blocks are silent and brutal to debug.
4. Share components between script blocks via
   `Object.assign(window, { Component1, Component2 })`.
5. Keep files under 1000 lines — split into multiple JSX blocks if
   needed.
6. Do not use `type="module"` on script imports — it may break things
   with Babel.
7. For simulations, Canvas is still preferred — React adds unnecessary
   overhead for physics engines.

## When to use React vs vanilla

| Task | Lane |
|------|------|
| Quiz widgets, multi-state UIs, forms, tab interfaces | React |
| Dashboards with KPI cards, charts, data tables | React |
| Physics simulations, particle systems, real-time rendering | Vanilla + Canvas |
| Animation loops with stateful slider readouts | Vanilla + Canvas + RAF |
| Search result explorers with filtered lists | React (or vanilla if simple) |
