/* Fundo vivo: ícones de som flutuando que seguem o cursor do mouse. */
(() => {
  const NS = 'http://www.w3.org/2000/svg';
  document.body.insertAdjacentHTML('afterbegin', `<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <symbol id="s-nota" viewBox="0 0 24 24"><path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/></symbol>
  <symbol id="s-mic" viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4"/></symbol>
  <symbol id="s-fone" viewBox="0 0 24 24"><path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="3" y="14" width="4" height="6" rx="1.5"/><rect x="17" y="14" width="4" height="6" rx="1.5"/></symbol>
  <symbol id="s-onda" viewBox="0 0 24 24"><path d="M3 12h1M7 8v8M11 4v16M15 7v10M19 10v4M22 12h-1"/></symbol>
  <symbol id="s-alto" viewBox="0 0 24 24"><path d="M4 9v6h4l5 4V5L8 9H4zM16 9a4 4 0 0 1 0 6M18.5 6.5a8 8 0 0 1 0 11"/></symbol>
</svg><div id="fundo" aria-hidden="true"></div>`);
  const box = document.getElementById('fundo');
  const ids = ['s-nota', 's-mic', 's-fone', 's-onda', 's-alto'];
  const icones = [];
  for (let i = 0; i < 22; i++) {
    const w = document.createElement('div'), s = document.createElementNS(NS, 'svg'), u = document.createElementNS(NS, 'use');
    const t = 28 + Math.random() * 70;
    w.className = 'ic';
    w.style.cssText = `left:${Math.random() * 96}%;top:${100 + Math.random() * 20}vh`;
    u.setAttribute('href', '#' + ids[i % ids.length]);
    s.append(u); s.setAttribute('viewBox', '0 0 24 24');
    s.style.cssText = `width:${t}px;height:${t}px;--o:${(0.07 + Math.random() * 0.14).toFixed(2)};` +
      `--r0:${Math.random() * 40 - 20}deg;--r1:${Math.random() * 80 - 40}deg;` +
      `animation-duration:${26 + Math.random() * 30}s;animation-delay:${-Math.random() * 50}s`;
    w.append(s); box.append(w);
    icones.push({ w, s, x: 0, y: 0, k: 1, prof: 0.5 + (t - 28) / 70 });  // ícones maiores reagem mais
  }
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  let mx = 0, my = 0, ativo = false;
  addEventListener('mousemove', e => { mx = e.clientX; my = e.clientY; ativo = true; }, { passive: true });
  document.documentElement.addEventListener('mouseleave', () => { ativo = false; });
  const RAIO = 280;
  (function quadro() {
    for (const ic of icones) {
      let tx = 0, ty = 0, tk = 1;
      if (ativo) {
        const r = ic.s.getBoundingClientRect();
        const dx = mx - (r.left + r.width / 2 - ic.x), dy = my - (r.top + r.height / 2 - ic.y);
        const d = Math.hypot(dx, dy);
        if (d < RAIO && d > 1) {
          const f = 1 - d / RAIO, mag = Math.min(d * 0.6, f * 90 * ic.prof);
          tx = dx / d * mag; ty = dy / d * mag; tk = 1 + f * 0.35;
        }
      }
      ic.x += (tx - ic.x) * 0.07; ic.y += (ty - ic.y) * 0.07; ic.k += (tk - ic.k) * 0.07;
      ic.w.style.transform = `translate3d(${ic.x.toFixed(1)}px,${ic.y.toFixed(1)}px,0) scale(${ic.k.toFixed(3)})`;
    }
    requestAnimationFrame(quadro);
  })();
})();
