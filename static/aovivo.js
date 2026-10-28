/* Gravação ao vivo: microfone e/ou áudio do computador -> trechos de fala -> transcrição em tempo real. */
(() => {
const $ = id => document.getElementById(id);
// Blocos menores deixam a legenda mais responsiva. O resumo fica para o final.
const TAXA = 16000, MIN_S = 2, MAX_S = 6, PAUSA_S = 0.35, LIMIAR = 0.01;
const fmt = s => { s = Math.floor(s); return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); };
const DICAS = {
  tiny: 'Mais rápida, mas erra mais palavras.',
  base: 'Recomendada para tempo real em computador sem placa de vídeo.',
  small: 'Mais precisa, porém pode ficar atrasada em relação à fala.'
};
let S = null;   // sessão de gravação ativa

const msg = (t, c) => { const m = $('av-msg'); m.className = c || ''; m.textContent = t || ''; };
fetch('/api/config').then(r => r.json()).then(c => {
  $('av-destino').replaceChildren(...c.pastas.map(d => {
    const o = document.createElement('option');
    o.value = d; o.textContent = d.replace(/\//g, ' / '); o.selected = d === c.padrao;
    return o;
  }));
});
$('av-modelo').onchange = () => { $('av-dica').textContent = DICAS[$('av-modelo').value]; };
$('av-modelo').onchange();

// medidor de volume animado
const vu = $('av-vu');
for (let i = 0; i < 40; i++) vu.append(document.createElement('i'));
const barras = [...vu.children], hist = new Array(barras.length).fill(0);
(function desenhar() {
  hist.push(S && S.ativo ? S.nivel : 0); hist.shift();
  barras.forEach((b, k) => { b.style.height = (4 + Math.min(1, hist[k] * 14) * 44) + 'px'; });
  requestAnimationFrame(desenhar);
})();

function ui(on) {
  ['av-fonte', 'av-modelo', 'av-idioma', 'av-titulo', 'av-destino', 'av-guardar'].forEach(id => { $(id).disabled = on; });
  $('av-ini').hidden = on; $('av-parar').hidden = !on; $('av-desc').hidden = !on;
  $('b-rec').classList.toggle('on', on);
}

setInterval(() => {
  if (!S) return;
  $('av-tempo').textContent = fmt((S.consumido + S.total) / TAXA);
  if (!S.ativo) return;
  $('av-estado').textContent = (S.fila.length || S.enviando)
    ? (S.recebeu ? 'Transcrevendo…' : 'Carregando o modelo (na 1ª vez pode demorar)…')
    : (S.nivel > LIMIAR ? 'Ouvindo fala…' : 'Ouvindo…');
}, 300);

function adicionar(seg) {
  const live = $('av-live');
  if (live.querySelector('.vazio')) live.replaceChildren();
  live.querySelectorAll('.legenda-pendente').forEach(p => p.remove());
  const p = document.createElement('p'), b = document.createElement('b');
  b.textContent = '[' + fmt(seg.ini) + ']';
  p.append(b, seg.texto);
  live.append(p);
  live.scrollTop = live.scrollHeight;
}

function indicarProcessamento(inicio) {
  const live = $('av-live');
  if (live.querySelector('.vazio')) live.replaceChildren();
  live.querySelectorAll('.legenda-pendente').forEach(p => p.remove());
  const p = document.createElement('p');
  p.className = 'legenda-pendente';
  p.textContent = '[' + fmt(inicio) + '] ouvindo e convertendo em legenda…';
  live.append(p);
  live.scrollTop = live.scrollHeight;
}

// ---- captura: acumula blocos e corta o trecho numa pausa (ou no máximo a cada 14 s) ----
function captar(s, x) {
  if (!s.ativo) return;
  if (s.sampleRate !== TAXA) {
    const escala = TAXA / s.sampleRate;
    const saida = new Float32Array(Math.max(1, Math.floor(x.length * escala)));
    for (let i = 0; i < saida.length; i++) {
      const inicio = Math.floor(i / escala), fim = Math.min(x.length, Math.max(inicio + 1, Math.floor((i + 1) / escala)));
      let soma = 0;
      for (let j = inicio; j < fim; j++) soma += x[j];
      saida[i] = soma / (fim - inicio);
    }
    x = saida;
  }
  let soma = 0;
  for (let i = 0; i < x.length; i++) soma += x[i] * x[i];
  const rms = Math.sqrt(soma / x.length);
  s.nivel = rms;
  s.buf.push(new Float32Array(x)); s.total += x.length;
  if (rms > LIMIAR) { s.fala = true; s.silencio = 0; } else s.silencio += x.length;
  const dur = s.total / TAXA;
  if ((dur >= MIN_S && s.silencio >= PAUSA_S * TAXA) || dur >= MAX_S) cortar(s);
}

function cortar(s) {
  const total = s.total, inicio = s.consumido / TAXA, tinhaFala = s.fala, blocos = s.buf;
  s.consumido += total; s.buf = []; s.total = 0; s.silencio = 0; s.fala = false;
  if (!tinhaFala || !total) return;           // só silêncio: não gasta processamento
  const pcm = new Int16Array(total); let o = 0;
  for (const b of blocos) for (let i = 0; i < b.length; i++) pcm[o++] = Math.max(-1, Math.min(1, b[i])) * 32767;
  s.fila.push({ inicio, pcm });
  indicarProcessamento(inicio);
  processarFila(s);
}

async function processarFila(s) {
  if (s.enviando) return;
  s.enviando = true;
  while (s.fila.length) {
    const it = s.fila.shift();
    try {
      const r = await fetch(`/api/ao-vivo/${s.id}/trecho`, { method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream', 'X-Inicio': String(it.inicio) }, body: it.pcm.buffer });
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.erro || 'erro ' + r.status);
      s.recebeu = true;
      j.segmentos.forEach(adicionar);
    } catch (e) { msg('Falha ao transcrever um trecho: ' + e.message, 'err'); s.recebeu = true; }
  }
  s.enviando = false;
}

function encerrar(s) {
  s.ativo = false;
  try { s.proc.disconnect(); } catch (e) {}
  s.streams.forEach(st => st.getTracks().forEach(t => t.stop()));
  s.ctx.close().catch(() => {});
}

async function iniciar() {
  const fonte = $('av-fonte').value, streams = [];
  $('av-live').replaceChildren(Object.assign(document.createElement('div'), { className: 'vazio', textContent: 'Aguardando fala…' }));
  $('av-fim').replaceChildren(); msg('Pedindo acesso ao áudio…');
  try {
    if (!navigator.mediaDevices) throw new Error('O navegador bloqueou o áudio. Abra o site por http://127.0.0.1:5055.');
    if (fonte !== 'sistema') streams.push(await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } }));
    if (fonte !== 'mic') {
      const d = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      streams.push(d);
      if (!d.getAudioTracks().length) throw new Error('Nenhum áudio foi compartilhado. Escolha “Tela inteira” ou uma guia e marque “Compartilhar áudio”.');
    }
  } catch (e) {
    streams.forEach(st => st.getTracks().forEach(t => t.stop()));
    return msg(e.name === 'NotAllowedError' ? 'Permissão negada. Libere o acesso e tente de novo.' : e.message, 'err');
  }
  const ctx = new AudioContext({ sampleRate: TAXA });
  if (ctx.sampleRate !== TAXA) { streams.forEach(st => st.getTracks().forEach(t => t.stop())); ctx.close(); return msg('Este navegador não suporta o áudio necessário. Use Chrome ou Edge.', 'err'); }
  const r = await fetch('/api/ao-vivo/iniciar', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ titulo: $('av-titulo').value, destino: $('av-destino').value, modelo: $('av-modelo').value, idioma: $('av-idioma').value }) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { streams.forEach(st => st.getTracks().forEach(t => t.stop())); ctx.close(); return msg(j.erro || 'Servidor desatualizado: feche e reabra o .bat.', 'err'); }

  const mix = ctx.createGain(), dest = ctx.createMediaStreamDestination();
  streams.forEach(st => { const a = st.getAudioTracks(); if (a.length) ctx.createMediaStreamSource(new MediaStream(a)).connect(mix); });
  mix.connect(dest);
  const proc = ctx.createScriptProcessor(4096, 1, 1), mudo = ctx.createGain();
  mudo.gain.value = 0; mix.connect(proc); proc.connect(mudo); mudo.connect(ctx.destination);

  const partes = []; let rec = null;
  if ($('av-guardar').checked && window.MediaRecorder) {
    rec = new MediaRecorder(dest.stream);
    rec.ondataavailable = e => { if (e.data.size) partes.push(e.data); };
    rec.start(5000);
  }
  const s = S = { id: j.id, titulo: $('av-titulo').value.trim() || 'gravacao', ctx, streams, proc, rec, partes, fila: [], enviando: false,
    consumido: 0, buf: [], total: 0, silencio: 0, fala: false, nivel: 0, ativo: true, recebeu: false };
  proc.onaudioprocess = e => captar(s, e.inputBuffer.getChannelData(0));
  const tela = streams.find(st => st.getVideoTracks().length);
  if (tela) tela.getTracks()[0].addEventListener('ended', () => parar(s));   // usuário clicou em "Parar compartilhamento"
  ui(true); msg('');
}

async function parar(s) {
  if (!s || !s.ativo) return;
  s.ativo = false;
  if (s.fala) cortar(s);
  $('av-estado').textContent = 'Finalizando…'; msg('Finalizando a transcrição…');
  const audioPronto = new Promise(res => { if (s.rec && s.rec.state !== 'inactive') { s.rec.onstop = res; s.rec.stop(); } else res(); });
  encerrar(s);
  while (s.enviando || s.fila.length) await new Promise(r => setTimeout(r, 200));
  await audioPronto;
  const fim = $('av-fim'); fim.replaceChildren();
  if (s.partes.length) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob(s.partes, { type: s.rec.mimeType || 'audio/webm' }));
    a.download = s.titulo.replace(/[^\w\- ]+/g, '').trim() + '.webm';
    a.textContent = 'Baixar o áudio (.webm)';
    fim.append(a);
  }
  const r = await fetch(`/api/ao-vivo/${s.id}/finalizar`, { method: 'POST' });
  const j = await r.json().catch(() => ({}));
  S = null; ui(false); $('av-estado').textContent = '';
  if (!r.ok) return msg(j.erro || 'Não consegui salvar a nota.', 'err');
  msg('');
  const ok = document.createElement('span'); ok.textContent = 'Pronto. Nota salva em ' + j.arquivo.replace(/\//g, ' / ') + '.';
  const ver = document.createElement('a'); ver.textContent = 'Ver no histórico'; ver.onclick = () => window.App.verHistorico(j.id);
  fim.prepend(ok, ver);
}

function descartar() {
  const s = S; if (!s) return;
  encerrar(s); S = null; ui(false);
  fetch(`/api/ao-vivo/${s.id}/cancelar`, { method: 'POST' });
  $('av-estado').textContent = ''; $('av-tempo').textContent = '00:00'; msg('Gravação descartada.');
}

$('av-ini').onclick = iniciar;
$('av-parar').onclick = () => parar(S);
$('av-desc').onclick = () => { if (confirm('Descartar esta gravação? A transcrição feita até aqui será perdida.')) descartar(); };
addEventListener('beforeunload', e => { if (S && S.ativo) { e.preventDefault(); e.returnValue = ''; } });
})();
