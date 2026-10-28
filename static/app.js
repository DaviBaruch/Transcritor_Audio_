(() => {
const _fetch = window.fetch.bind(window);
window.fetch = async (...a) => { const r = await _fetch(...a); if (r.status === 401) location.href = '/login'; return r; };
const $ = id => document.getElementById(id);
const estado = { cfg: null, itens: [], filtro: 'todas', busca: '', sel: null, view: 'transcrever' };

function iniciarBarraAjustavel() {
  const app = document.querySelector('.app'), side = document.querySelector('.side'), handle = $('resize-handle');
  if (!app || !side || !handle) return;
  const salvo = Number(localStorage.getItem('largura-barra-lateral'));
  if (salvo >= 180 && salvo <= 420) side.style.width = salvo + 'px';
  let arrastando = false;
  const mover = e => { if (!arrastando) return; const largura = Math.max(180, Math.min(420, e.clientX)); side.style.width = largura + 'px'; };
  const parar = () => { if (!arrastando) return; arrastando = false; app.classList.remove('redimensionando'); localStorage.setItem('largura-barra-lateral', parseInt(side.getBoundingClientRect().width, 10)); };
  handle.addEventListener('pointerdown', e => { if (e.pointerType === 'mouse' || e.pointerType === 'pen' || e.pointerType === 'touch') { arrastando = true; app.classList.add('redimensionando'); handle.setPointerCapture(e.pointerId); } });
  handle.addEventListener('pointermove', mover); handle.addEventListener('pointerup', parar); handle.addEventListener('pointercancel', parar);
  handle.addEventListener('keydown', e => { const atual = side.getBoundingClientRect().width; if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); const n = Math.max(180, Math.min(420, atual + (e.key === 'ArrowRight' ? 10 : -10))); side.style.width = n + 'px'; localStorage.setItem('largura-barra-lateral', n); } });
}

function el(tag, props, ...filhos) {
  const n = document.createElement(tag);
  Object.entries(props || {}).forEach(([k, v]) => {
    if (k === 'class') n.className = v;
    else if (k === 'text') n.textContent = v;
    else if (k.startsWith('on')) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  });
  filhos.flat().forEach(f => f != null && n.append(f.nodeType ? f : document.createTextNode(f)));
  return n;
}
const fmtData = d => d ? d.split('-').reverse().join('/') : '';
function fmtDur(s) {
  if (s < 60) return s + ' s';
  const m = Math.round(s / 60);
  return m < 60 ? m + ' min' : Math.floor(m / 60) + 'h' + String(m % 60).padStart(2, '0');
}
const caminho = rel => rel.replace(/\//g, ' / ');
function aplicarPerfil(p) {
  document.body.dataset.tema = p.tema || 'aurora';
  $('user').textContent = p.usuario || '';
  ['avatar-img', 'perfil-img'].forEach(id => { $(id).src = p.foto || ''; $(id).classList.toggle('hidden', !p.foto); });
  ['avatar-letra', 'perfil-letra'].forEach(id => { $(id).textContent = (p.usuario || '?')[0].toUpperCase(); $(id).classList.toggle('hidden', !!p.foto); });
}

const DICAS = {
  base: 'Rápido. Estimativa: ~6 min de espera por hora de áudio (medido em áudio limpo).',
  small: 'Equilibrado. Estimativa: ~15 min de espera por hora de áudio (medido em áudio limpo). Baixa ~460 MB na 1ª vez.',
  medium: 'Mais preciso e mais lento que o small (tempo não medido). Baixa um modelo grande na 1ª vez.'
};

function mostrar(view) {
  estado.view = view === 'transcrever' ? 'transcrever' : (view === 'ao-vivo' ? 'ao-vivo' : 'historico');
  if (view === 'historico') estado.filtro = 'todas';
  if (view === 'organizar') estado.filtro = 'inbox';
  $('v-transcrever').classList.toggle('hidden', estado.view !== 'transcrever');
  $('v-historico').classList.toggle('hidden', estado.view !== 'historico');
  $('v-ao-vivo').classList.toggle('hidden', estado.view !== 'ao-vivo');
  document.querySelectorAll('.nav').forEach(b => {
    const on = estado.view === 'transcrever' ? b.dataset.nav === 'transcrever'
      : estado.view === 'ao-vivo' ? b.dataset.nav === 'ao-vivo'
      : b.dataset.nav === (estado.filtro === 'inbox' ? 'organizar' : 'historico');
    b.classList.toggle('on', on);
  });
  if (estado.view === 'historico') carregarHistorico();
}

async function carregarHistorico() {
  estado.itens = await (await fetch('/api/historico')).json();
  const pend = estado.itens.filter(i => i.estado === 'inbox').length;
  $('b-todas').textContent = estado.itens.length || '';
  $('b-pend').textContent = pend || '';
  desenharLista();
  if (estado.sel && estado.itens.some(i => i.id === estado.sel)) abrirItem(estado.sel);
  else desenharVazio();
}

function filtrados() {
  const q = estado.busca.trim().toLowerCase();
  return estado.itens.filter(i =>
    (estado.filtro === 'todas' || i.estado === estado.filtro) &&
    (!q || (i.titulo + ' ' + i.pasta + ' ' + i.resumo.join(' ')).toLowerCase().includes(q)));
}

function desenharLista() {
  document.querySelectorAll('.chip').forEach(c => c.classList.toggle('on', c.dataset.f === estado.filtro));
  const lista = $('lista');
  lista.replaceChildren();
  const itens = filtrados();
  if (!itens.length) {
    lista.append(el('div', { class: 'vazio', text: estado.itens.length ? 'Nada encontrado com esse filtro.' : 'Nenhuma transcrição ainda.' }));
    return;
  }
  itens.forEach(i => {
    const lixo = el('button', { class: 'lixo', title: 'Excluir', 'aria-label': 'Excluir ' + i.titulo,
      onclick: ev => { ev.stopPropagation(); pedirExclusao(i); } });
    lixo.innerHTML = ICONE_LIXO;
    lista.append(el('div', { class: 'row-wrap' },
      el('button', { class: 'row' + (i.id === estado.sel ? ' on' : ''), onclick: () => abrirItem(i.id) },
        el('div', { class: 'row-t' }, el('span', { class: 'dot ' + i.estado }), el('span', { class: 't', text: i.titulo })),
        el('div', { class: 'row-m', text: `${fmtData(i.criado)} · ${fmtDur(i.duracao)} · ${i.pasta || 'arquivo não encontrado'}` })),
      lixo));
  });
}

const ICONE_LIXO = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6"/></svg>';

function pedirExclusao(i) {
  const dlg = $('dlg-del'), btns = ['del-hist', 'del-nota'];
  $('del-p').textContent = `“${i.titulo}” · ${fmtData(i.criado)}`;
  $('del-msg').textContent = ''; $('del-cancel').textContent = 'Cancelar';
  btns.forEach(id => { $(id).disabled = false; });
  $('op-nota').classList.toggle('hidden', i.estado === 'ausente');
  const enviar = async nota => {
    btns.forEach(id => { $(id).disabled = true; });
    let r, j = {};
    try {
      r = await fetch('/api/item/' + i.id, { method: 'DELETE', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nota }) });
      j = await r.json().catch(() => ({}));
    } catch (e) { r = { ok: false, status: 0 }; }
    if (!r.ok) {
      $('del-msg').textContent = j.erro || (r.status === 404 || r.status === 405 || r.status === 0
        ? 'O servidor está desatualizado ou parado: feche a janela preta do .bat e abra de novo.' : 'Falha ao excluir (erro ' + r.status + ').');
      btns.forEach(id => { $(id).disabled = false; }); return;
    }
    if (estado.sel === i.id) estado.sel = null;
    carregarHistorico();
    if (j.aviso) { $('del-msg').textContent = j.aviso; $('del-cancel').textContent = 'Fechar'; } else dlg.close();
  };
  $('del-hist').onclick = () => enviar(false);
  $('del-nota').onclick = () => enviar(true);
  $('del-cancel').onclick = () => dlg.close();
  dlg.showModal();
}

function desenharVazio() {
  $('detalhe').replaceChildren(el('div', { class: 'vazio', text: 'Selecione uma transcrição para ver o resumo.' }));
}

function secaoLista(titulo, itens, cls) {
  if (!itens.length) return null;
  return [el('h3', { text: titulo }), el('ul', {}, itens.map(t => el('li', { class: cls || '', text: t })))];
}

function secaoTexto(titulo, texto) {
  if (!texto) return null;
  const corpo = texto.split(/\n+/).filter(Boolean).map(linha =>
    el('p', { text: linha.replace(/^#{1,6}\s+/, '').replace(/^[-*]\s+/, '') }));
  return [el('h3', { text: titulo }), el('div', { class: 'interpretacao-ia' }, corpo)];
}

async function abrirItem(id) {
  estado.sel = id;
  desenharLista();
  const r = await fetch('/api/item/' + id);
  if (!r.ok) { desenharVazio(); return; }
  const d = await r.json();
  const rotulo = { inbox: 'Para organizar', organizada: 'Organizada', ausente: 'Arquivo não encontrado' }[d.estado];

  const sel = el('select', { id: 'sel-pasta' }, el('option', { value: '', text: 'Escolha a pasta...' }),
    estado.cfg.pastas.map(p => el('option', { value: p, text: caminho(p) })));
  const res = el('div', { class: 'res' });
  const btn = el('button', { class: 'btn', text: 'Mover e ligar ao índice', onclick: async () => {
    if (!sel.value) { res.className = 'res err'; res.textContent = 'Escolha uma pasta.'; return; }
    btn.disabled = true;
    const rr = await fetch('/api/organizar/' + id, { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pasta: sel.value }) });
    const j = await rr.json();
    if (!rr.ok) { res.className = 'res err'; res.textContent = j.erro; btn.disabled = false; return; }
    await carregarHistorico();
    const r2 = $('detalhe').querySelector('.res');
    if (r2) { r2.className = 'res ok'; r2.textContent = j.moc ? `Movida e ligada em [[${j.moc}]].` : (j.aviso || 'Movida.'); }
  } });

  const transc = d.transcricao.length
    ? el('details', {}, el('summary', { text: `Transcrição completa (${d.transcricao.length} blocos)` }),
        d.transcricao.map(p => {
          const m = p.match(/^\*\*\[([^\]]+)\]\*\*\s*([\s\S]*)$/);
          return el('div', { class: 'par' }, m ? [el('b', { text: m[1] }), m[2]] : p);
        }))
    : null;

  $('detalhe').replaceChildren(el('div', { class: 'det' },
    el('h2', { text: d.titulo }),
    el('div', { class: 'meta' }, el('span', { class: 'dot ' + d.estado }), rotulo, '·', fmtData(d.criado), '·', fmtDur(d.duracao), '·',
      'modelo ' + d.modelo, d.termos.slice(0, 4).map(t => el('span', { class: 'tag', text: t }))),
    secaoLista('Resumo', d.resumo),
    secaoTexto('Interpretação IA', d.interpretacao_ia),
    d.resumo.length ? el('div', { class: 'nota-fraca', text: 'Resumo extrativo: seleciona frases da fala. Revise antes de confiar nos detalhes.' }) : null,
    secaoLista('Ações e prazos', d.acoes, 'ac'),
    el('h3', { text: 'Transcrição' }), transc || el('div', { class: 'nota-fraca', text: 'Arquivo da nota não encontrado.' }),
    d.estado === 'ausente' ? null : el('div', { class: 'org' },
      el('label', { class: 'lbl', text: 'Organizar' }),
      el('div', { class: 'atual', text: 'Local atual: ' + caminho(d.pasta) }),
      el('div', { class: 'ac-row' }, sel, btn), res)));
}

function iniciarTranscrever() {
  let arquivo = null;
  const dica = () => { $('dica').textContent = DICAS[$('modelo').value]; };
  const setArq = f => {
    if (!f) return;
    arquivo = f;
    $('arq').textContent = `${f.name} (${(f.size / 1048576).toFixed(1)} MB)`;
    if (!$('titulo').value) $('titulo').value = f.name.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ');
    $('go').disabled = false;
  };
  const msg = (t, c, html) => { const m = $('msg'); m.className = c || ''; m.replaceChildren(...(html || [t])); };

  $('modelo').onchange = dica; dica();
  $('drop').onclick = () => $('file').click();
  $('drop').onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') $('file').click(); };
  $('file').onchange = e => setArq(e.target.files[0]);
  ['dragover', 'dragenter'].forEach(ev => $('drop').addEventListener(ev, e => { e.preventDefault(); $('drop').classList.add('on'); }));
  ['dragleave', 'drop'].forEach(ev => $('drop').addEventListener(ev, e => { e.preventDefault(); $('drop').classList.remove('on'); }));
  $('drop').addEventListener('drop', e => setArq(e.dataTransfer.files[0]));

  $('go').onclick = async () => {
    $('go').disabled = true;
    $('barra').style.display = 'block';
    $('barra').firstChild.style.width = '2%';
    msg('Enviando áudio...');
    const fd = new FormData();
    fd.append('audio', arquivo);
    ['titulo', 'destino', 'modelo', 'idioma'].forEach(k => fd.append(k, $(k).value));
    const r = await fetch('/enviar', { method: 'POST', body: fd });
    const j = await r.json();
    if (!r.ok) { msg(j.erro || 'Falha no envio', 'err'); $('go').disabled = false; return; }
    const t = setInterval(async () => {
      const s = await (await fetch('/status/' + j.id)).json();
      $('barra').firstChild.style.width = Math.max(2, Math.round(s.progresso * 100)) + '%';
      if (s.estado === 'fila') msg('Na fila (outro áudio está sendo processado)...');
      else if (s.estado === 'processando')
        msg(s.progresso <= 0.01 ? 'Carregando o modelo (na 1ª vez baixa o arquivo)...' : 'Transcrevendo... ' + Math.round(s.progresso * 100) + '%');
      else if (s.estado === 'ok') {
        clearInterval(t);
        estado.sel = s.item;
        const ver = el('a', { text: 'Ver no histórico', onclick: () => mostrar('historico') });
        msg('', 'ok', ['Pronto. Nota salva em ' + caminho(s.arquivo) + '. ', ver]);
        $('go').disabled = false;
        carregarHistorico();
      } else if (s.estado === 'erro') { clearInterval(t); msg('Erro: ' + s.erro, 'err'); $('go').disabled = false; }
    }, 1200);
  };
}

window.App = { verHistorico: id => { estado.sel = id; mostrar('historico'); abrirItem(id); } };

async function iniciar() {
  iniciarBarraAjustavel();
  const appShell = document.querySelector('.app');
  const alternarMenu = aberto => {
    appShell.classList.toggle('menu-aberto', aberto);
    $('menu-toggle').setAttribute('aria-expanded', String(aberto));
    $('menu-toggle').textContent = aberto ? '×' : '☰';
  };
  $('menu-toggle').onclick = () => alternarMenu(!appShell.classList.contains('menu-aberto'));
  $('menu-backdrop').onclick = () => alternarMenu(false);
  estado.cfg = await (await fetch('/api/config')).json();
  fetch('/api/perfil').then(r => r.json()).then(p => { aplicarPerfil(p); $('tema').value = p.tema || 'aurora'; });
  $('sair').onclick = async () => { $('user').textContent = ''; if ($('usuario')) $('usuario').value = ''; if ($('senha')) $('senha').value = ''; await fetch('/api/sair', { method: 'POST' }); location.href = '/login'; };
  $('perfil-btn').onclick = () => $('dlg-perfil').showModal();
  $('perfil-foto-btn').onclick = () => $('perfil-arquivo').click();
  $('perfil-arquivo').onchange = e => { const f = e.target.files[0]; if (!f) return; const r = new FileReader(); r.onload = () => { $('perfil-img').src = r.result; $('perfil-img').classList.remove('hidden'); $('perfil-letra').classList.add('hidden'); $('perfil-img').dataset.nova = r.result; }; r.readAsDataURL(f); };
  $('perfil-fechar').onclick = () => $('dlg-perfil').close();
  $('perfil-salvar').onclick = async () => { const foto = $('perfil-img').dataset.nova || ($('perfil-img').src.startsWith('data:') ? $('perfil-img').src : ''); const r = await fetch('/api/perfil', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ tema: $('tema').value, foto }) }); const j = await r.json(); if (!r.ok) { $('perfil-msg').textContent = j.erro; return; } const p = await (await fetch('/api/perfil')).json(); aplicarPerfil(p); $('dlg-perfil').close(); };
  $('destino').replaceChildren(...estado.cfg.pastas.map(d =>
    el('option', { value: d, text: caminho(d), ...(d === estado.cfg.padrao ? { selected: 'selected' } : {}) })));
  $('nova-pasta').onclick = async () => {
    const nome = prompt('Nome da nova pasta:');
    if (!nome || !nome.trim()) return;
    const pai = estado.cfg.pastas[0] || '';
    const r = await fetch('/api/pastas', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ nome: nome.trim(), pai }) });
    const j = await r.json();
    if (!r.ok) { alert(j.erro || 'Não foi possível criar a pasta.'); return; }
    estado.cfg = await (await fetch('/api/config')).json();
    $('destino').replaceChildren(...estado.cfg.pastas.map(p => el('option', { value: p, text: caminho(p), ...(p === j.pasta ? { selected: 'selected' } : {}) })));
    if (typeof window.atualizarPastasAoVivo === 'function') window.atualizarPastasAoVivo(estado.cfg.pastas);
  };
  $('importar-pastas').onclick = () => {
    const input = $('pasta-computador');
    const celular = matchMedia('(max-width: 700px)').matches;
    if (celular) { input.removeAttribute('webkitdirectory'); input.removeAttribute('directory'); }
    else { input.setAttribute('webkitdirectory', ''); input.setAttribute('directory', ''); }
    input.click();
  };
  $('pasta-computador').onchange = async e => {
    const caminhos = [...e.target.files].map(f => f.webkitRelativePath || f.name).filter(Boolean);
    if (!caminhos.length) return;
    let criadas = 0;
    for (let i = 0; i < caminhos.length; i += 1000) {
      const r = await fetch('/api/pastas/importar', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ caminhos: caminhos.slice(i, i + 1000) }) });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) { alert(j.erro || 'Não foi possível importar as pastas.'); return; }
      criadas += j.criadas || 0;
    }
    estado.cfg = await (await fetch('/api/config')).json();
    alert(`${criadas} pasta(s) importada(s).`); e.target.value = '';
  };
  document.querySelectorAll('.nav').forEach(b => b.onclick = () => { mostrar(b.dataset.nav); alternarMenu(false); });
  document.querySelectorAll('.chip').forEach(c => c.onclick = () => {
    estado.filtro = c.dataset.f;
    document.querySelectorAll('.nav').forEach(b =>
      b.classList.toggle('on', b.dataset.nav === (estado.filtro === 'inbox' ? 'organizar' : 'historico')));
    desenharLista();
  });
  $('busca').oninput = e => { estado.busca = e.target.value; desenharLista(); };
  iniciarTranscrever();
  mostrar('transcrever');
  fetch('/api/historico').then(r => r.json()).then(h => {
    $('b-todas').textContent = h.length || '';
    $('b-pend').textContent = h.filter(i => i.estado === 'inbox').length || '';
  });
}
iniciar();
})();
