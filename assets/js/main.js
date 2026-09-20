// Theme toggle: light → dark → follow system, remembered per browser.
(function () {
  var root = document.documentElement;
  var btn = document.querySelector('[data-theme-toggle]');
  if (!btn) return;

  var label = btn.querySelector('.theme-label');

  function current() {
    return root.getAttribute('data-theme') || 'system';
  }

  function paint() {
    var mode = current();
    if (label) label.textContent = mode.charAt(0).toUpperCase() + mode.slice(1);
    btn.setAttribute('aria-label', 'Colour theme: ' + mode + '. Click to change.');
  }

  btn.addEventListener('click', function () {
    var order = ['light', 'dark', 'system'];
    var next = order[(order.indexOf(current()) + 1) % order.length];
    if (next === 'system') {
      root.removeAttribute('data-theme');
      try { localStorage.removeItem('theme'); } catch (e) {}
    } else {
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('theme', next); } catch (e) {}
    }
    paint();
  });

  paint();
})();
