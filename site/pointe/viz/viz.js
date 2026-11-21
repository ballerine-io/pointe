// The orchestra figure (tools/orchestra_viz.py draws it, viz.css styles it). Three short scenes play in turn while the
// figure is on screen and the tab is in front: a send by name, an approval, a question about every machine. With reduced
// motion nothing plays: each scene is a still, picked from the list under the figure. Only transforms and opacities move.
(() => {
  const root = document.querySelector('[data-orch]');
  if (!root || !root.animate || !window.IntersectionObserver) return;
  const NS = 'http://www.w3.org/2000/svg';
  const still = matchMedia('(prefers-reduced-motion: reduce)');
  const all = sel => [...root.querySelectorAll(sel)];
  const say = root.querySelector('.o-say'), who = say.querySelector('.o-who'), line = say.querySelector('.o-line');
  const BASE = { shop: 'working', docs: 'idle', 'river-lantern': 'idle', billing: 'idle', ingest: 'working', notes: 'working', api: 'idle' };
  const MACHINES = ['studio', 'devbox', 'laptop'], WIRES = ['phone', 'devbox', 'laptop', 'studio'];
  const SIZES = [5, 4.4, 3.8, 3.2, 2.7, 2.2], TRAVEL = 1000;

  // What the drawing can show
  const drawing = () => all('.o-svg').find(s => s.getBoundingClientRect().width > 0);
  const state = (name, s) => all(`[data-s="${name}"]`).forEach(r => { r.dataset.state = s; });
  const hot = (name, on = true) => all(`[data-s="${name}"]`).forEach(r => r.classList.toggle('is-hot', on));
  const lit = (name, on = true) => all(`[data-m="${name}"]`).forEach(g => g.classList.toggle('is-lit', on));
  const wire = (name, on = true) => all(`[data-wire="${name}"]`).forEach(p => p.classList.toggle('is-hot', on));
  const phone = ask => { ask ? root.dataset.phone = 'ask' : delete root.dataset.phone; };
  const press = on => all('.o-approve').forEach(b => b.classList.toggle('is-pressed', on));
  const quiet = () => { delete root.dataset.voice; };
  const speak = (by, label, text) => {
    who.textContent = label;
    say.dataset.by = by;
    line.classList.remove('is-in');
    line.replaceChildren(...text.split(' ').flatMap((w, i) => {
      const s = document.createElement('span');
      s.textContent = w;
      s.style.transitionDelay = `${i * 55}ms`;
      return i ? [' ', s] : [s];
    }));
    say.classList.remove('is-out');
    root.dataset.voice = by;
    line.getBoundingClientRect();  // so the words start from hidden
    line.classList.add('is-in');
  };
  const along = (name, at) => {
    const path = drawing().querySelector(`[data-route="${name}"]`);
    return path.getPointAtLength(path.getTotalLength() * at);
  };
  const dot = (r, name) => {
    const c = document.createElementNS(NS, 'circle');
    c.setAttribute('r', r);
    c.setAttribute('class', 'o-dot');
    drawing().querySelector('.o-trains').append(c);
    return c;
  };
  // A wave of dots along a wire: out from the point, or back to it
  const train = (name, back = false) => {
    const steps = 28, points = [];
    for (let i = 0; i <= steps; i++) points.push(along(name, back ? 1 - i / steps : i / steps));
    const frames = points.map((p, i) => ({ transform: `translate(${p.x}px, ${p.y}px)`, opacity: i < 2 || i === steps ? 0 : 1 }));
    wire(name);
    SIZES.forEach((r, k) => {
      const c = dot(r, name);
      const a = c.animate(frames, { duration: TRAVEL, delay: k * 55, easing: 'cubic-bezier(.5, 0, .3, 1)', fill: 'both' });
      a.onfinish = () => c.remove();
      moving.push(a);
    });
    at(now() + TRAVEL + 500, () => wire(name, false));
  };
  // The same wave, standing still
  const trail = (name, back = false) => {
    wire(name);
    SIZES.forEach((r, k) => {
      const p = along(name, back ? .46 + k * .035 : .62 - k * .035);
      const c = dot(r, name);
      c.setAttribute('transform', `translate(${p.x} ${p.y})`);
      c.setAttribute('opacity', 1 - k * .13);
    });
  };
  const ripple = (inward = false) => {
    const rings = [...drawing().querySelectorAll('.o-ring')];
    rings.forEach((g, i) => moving.push(g.animate([{ opacity: 1, transform: 'scale(1.035)', offset: .4 }],
      { duration: 760, delay: (inward ? rings.length - 1 - i : i) * 85, easing: 'ease-out' })));
  };

  // The clock of one scene: steps at set times, which a pause holds and a resume picks up
  let steps = [], timers = [], moving = [], began = 0, held = 0, scene = 0, started = false;
  const now = () => performance.now() - began;
  const arm = step => timers.push(setTimeout(() => { step.done = true; step.fn(); }, Math.max(0, step.ms - now())));
  const at = (ms, fn) => { const step = { ms, fn, done: false }; steps.push(step); if (running()) arm(step); };
  const clear = () => {
    timers.forEach(clearTimeout);
    moving.forEach(a => a.cancel());
    steps = []; timers = []; moving = [];
    all('.o-trains').forEach(l => l.replaceChildren());
    for (const [name, s] of Object.entries(BASE)) { state(name, s); hot(name, false); }
    MACHINES.forEach(m => lit(m, false));
    WIRES.forEach(w => wire(w, false));
    phone(false); press(false); quiet();
    say.classList.add('is-out');
  };

  const SCENES = [
    { ms: 8000,
      play() {
        speak('you', 'You', 'Ask billing on devbox to run the tests.');
        at(1150, () => ripple());
        at(1350, () => train('devbox'));
        at(1700, quiet);
        at(2350, () => { lit('devbox'); hot('billing'); state('billing', 'working'); });
        at(3400, () => lit('devbox', false));
        at(4500, () => train('devbox', true));
        at(5450, () => { ripple(true); hot('billing', false); state('billing', 'idle'); speak('pointe', 'Pointe', 'billing on devbox: 212 tests passed.'); });
        at(7000, quiet);
      },
      still() {
        speak('you', 'You', 'Ask billing on devbox to run the tests.');
        trail('devbox'); lit('devbox'); hot('billing'); state('billing', 'working');
      } },
    { ms: 9000,
      play() {
        state('notes', 'approve'); hot('notes'); lit('laptop');
        at(250, () => train('laptop', true));
        at(1200, () => { ripple(true); lit('laptop', false); speak('pointe', 'Pointe', 'notes on laptop wants to run npm test. Should it?'); });
        at(1500, () => train('phone'));
        at(2450, () => phone(true));
        at(3000, quiet);
        at(4700, () => { press(true); speak('you', 'You · a tap on the phone', 'Approve.'); });
        at(4900, () => { press(false); train('phone', true); });
        at(5300, () => phone(false));
        at(5850, () => { quiet(); train('laptop'); });
        at(6850, () => { lit('laptop'); state('notes', 'working'); });
        at(7700, () => { lit('laptop', false); hot('notes', false); });
      },
      still() {
        speak('pointe', 'Pointe', 'notes on laptop wants to run npm test. Should it?');
        state('notes', 'approve'); hot('notes'); lit('laptop'); trail('laptop', true); trail('phone'); phone(true);
      } },
    { ms: 8400,
      play() {
        speak('you', 'You', 'What’s going on everywhere?');
        at(1100, () => ripple());
        at(1500, () => { quiet(); MACHINES.forEach((m, i) => at(now() + i * 160, () => train(m, true))); });
        at(2800, () => { ripple(true); speak('pointe', 'Pointe', 'studio: shop is working. devbox: ingest is working. laptop: notes is testing.'); });
        at(2900, () => { lit('studio'); hot('shop'); });
        at(4100, () => { lit('studio', false); hot('shop', false); lit('devbox'); hot('ingest'); });
        at(5300, () => { lit('devbox', false); hot('ingest', false); lit('laptop'); hot('notes'); });
        at(6500, () => { lit('laptop', false); hot('notes', false); quiet(); });
      },
      still() {
        speak('pointe', 'Pointe', 'studio: shop is working. devbox: ingest is working. laptop: notes is testing.');
        MACHINES.forEach(m => lit(m));
        trail('devbox', true);
        ['shop', 'ingest', 'notes'].forEach(s => hot(s));
      } },
  ];

  // The list under the figure picks a scene; one button stops and starts the play
  const tabs = all('.o-tabs li').map((li, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.append(...li.childNodes);
    li.append(b);
    b.addEventListener('click', () => { stopped = false; label(); show(i); });
    return li;
  });
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'o-pause';
  root.querySelector('.o-foot').prepend(button);
  let stopped = false, seen = false;
  const label = () => { button.textContent = stopped ? 'Play' : 'Pause'; button.hidden = still.matches; };
  const running = () => !still.matches && !stopped && seen && !document.hidden;

  const show = i => {
    scene = i;
    held = 0;
    clear();
    tabs.forEach((li, k) => {
      li.classList.remove('is-on');
      li.querySelector('button').removeAttribute('aria-current');
      li.style.setProperty('--o-dur', `${SCENES[k].ms}ms`);
    });
    tabs[i].getBoundingClientRect();  // so the line above the name starts again
    tabs[i].classList.add('is-on');
    tabs[i].querySelector('button').setAttribute('aria-current', 'true');
    if (still.matches) { SCENES[i].still(); quiet(); return; }
    began = performance.now();
    started = true;
    SCENES[i].play();
    at(SCENES[i].ms - 350, () => say.classList.add('is-out'));
    at(SCENES[i].ms, () => show((i + 1) % SCENES.length));
  };
  const sync = () => {
    root.classList.toggle('is-live', !still.matches);
    if (still.matches) { root.classList.remove('is-paused'); if (drawing()) show(scene); return; }
    if (running()) {
      root.classList.remove('is-paused');
      if (!started) { show(scene); return; }
      began = performance.now() - held;
      moving.forEach(a => { if (a.playState === 'paused') a.play(); });
      timers.forEach(clearTimeout);
      timers = [];
      steps.filter(s => !s.done).forEach(arm);
    } else if (started && !root.classList.contains('is-paused')) {
      held = now();
      timers.forEach(clearTimeout);
      timers = [];
      moving.forEach(a => { if (a.playState === 'running') a.pause(); });
      root.classList.add('is-paused');
    }
  };

  root.classList.add('is-ready');
  clear();
  label();
  button.addEventListener('click', () => { stopped = !stopped; label(); sync(); });
  document.addEventListener('visibilitychange', sync);
  still.addEventListener('change', () => { started = false; clear(); label(); sync(); });
  new IntersectionObserver(entries => { seen = entries[entries.length - 1].isIntersecting; sync(); }, { threshold: .25 }).observe(root);
  if (still.matches) sync();
})();
