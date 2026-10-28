#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
transcritor.py — motor do Transcritor de Audio do segundo cerebro (custo 0).

Fluxo: audio -> faster-whisper (local, offline apos baixar o modelo) -> resumo
extrativo -> nota .md no padrao do vault (frontmatter, wiki-links, PascalCase).

Uso direto (sem interface):
  python transcritor.py caminho/do/audio.mp3 --titulo "Aula Banco de Dados"
  python transcritor.py audio.m4a --titulo "Reuniao Projeto" --destino 03_Projetos
"""

import argparse
import hashlib
import json
import math
import os
import re
import unicodedata
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
DESTINO_PADRAO = "00_Inbox"
MODELOS = ("tiny", "base", "small", "medium")
MODELO_PADRAO = "small"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
OLLAMA_MODELO = "qwen2.5:3b"
OLLAMA_ATIVO = os.getenv(
    "TRANSCRITOR_OLLAMA_ENABLED",
    "0" if os.getenv("TRANSCRITOR_PUBLIC_MODE", "0") == "1" else "1",
) == "1"
IA_CACHE = Path(__file__).resolve().parent / "cache_interpretacoes.json"

STOPWORDS = set("""
a o as os um uma uns umas de do da dos das em no na nos nas por para pra com sem sob sobre entre ate
e ou mas se que como quando onde porque pois porem entao assim tambem ainda ja so apenas muito muita
muitos muitas mais menos tao tanto tanta pouco poucos ser estar ter haver fazer ir vir poder dever
eu tu ele ela nos vos eles elas me te lhe lhes meu minha meus minhas teu tua seu sua seus suas nosso
nossa isso isto aquilo esse essa esses essas este esta estes estas aquele aquela aqueles aquelas
aqui ali la ca ai ne ta tá né então não nao sim tipo cara gente coisa coisas vez vezes bem agora
depois antes hoje era foi sao são esta estao estão tem tinha temos vai vou vamos va fica ficar
ha houve sendo sido tendo fazendo pode podem podemos precisa precisamos deve devemos so mesmo
cada todo toda todos todas outro outra outros outras qual quais quem quanto quanta algum alguma
alguns algumas nenhum nenhuma nada tudo algo
""".split())


def sem_acento(texto):
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def pascal_case(texto):
    limpo = re.sub(r"[^A-Za-z0-9]+", " ", sem_acento(texto)).strip()
    particulas = {"de", "da", "do", "das", "dos", "e", "em"}
    tokens = [t if (i and t.lower() in particulas) else t[:1].upper() + t[1:]
              for i, t in enumerate(limpo.split())]
    return "_".join(tokens) or "Transcricao"


def slug_tag(palavra):
    return re.sub(r"[^a-z0-9]+", "-", sem_acento(palavra.lower())).strip("-")


def fmt_tempo(segundos):
    s = int(segundos)
    h, resto = divmod(s, 3600)
    m, s = divmod(resto, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def listar_destinos(vault=None):
    vault = vault or VAULT
    pastas = sorted(p.name for p in vault.iterdir()
                    if p.is_dir() and re.match(r"^0[0-6]_|^0[89]_", p.name)
                    and p.name != "07_Arquivo")
    return pastas or [DESTINO_PADRAO]


_modelos_carregados = {}


def carregar_modelo(nome):
    if nome not in MODELOS:
        raise ValueError(f"Modelo invalido: {nome}")
    if nome not in _modelos_carregados:
        from faster_whisper import WhisperModel
        _modelos_carregados[nome] = WhisperModel(nome, device="cpu", compute_type="int8")
    return _modelos_carregados[nome]


def transcrever(caminho_audio, modelo=MODELO_PADRAO, idioma="pt", progresso=None):
    """Retorna (segmentos[(inicio, fim, texto)], duracao_s, idioma_detectado)."""
    wm = carregar_modelo(modelo)
    lang = None if idioma in (None, "", "auto") else idioma
    gen, info = wm.transcribe(str(caminho_audio), language=lang, vad_filter=True,
                              beam_size=1, condition_on_previous_text=False)
    segmentos = []
    for seg in gen:
        texto = seg.text.strip()
        if texto:
            segmentos.append((seg.start, seg.end, texto))
        if progresso and info.duration:
            progresso(min(seg.end / info.duration, 1.0))
    return segmentos, info.duration, info.language


def agrupar_paragrafos(segmentos, janela=45.0, pausa=2.5):
    """Junta segmentos em paragrafos: quebra a cada ~janela s ou numa pausa longa."""
    paragrafos, atual, inicio, ultimo_fim = [], [], None, 0.0
    for ini, fim, texto in segmentos:
        if atual and (ini - ultimo_fim > pausa or ini - inicio > janela):
            paragrafos.append((inicio, " ".join(atual)))
            atual, inicio = [], None
        if inicio is None:
            inicio = ini
        atual.append(texto)
        ultimo_fim = fim
    if atual:
        paragrafos.append((inicio, " ".join(atual)))
    return paragrafos


def palavras_relevantes(texto):
    return [p for p in re.findall(r"[a-záéíóúâêôãõàçü0-9]+", texto.lower())
            if len(p) > 3 and p not in STOPWORDS and sem_acento(p) not in STOPWORDS]


def resumir(texto_completo, max_frases=None):
    """Resumo EXTRATIVO: escolhe as frases mais representativas (sem IA generativa)."""
    frases = [f.strip() for f in re.split(r"(?<=[.!?])\s+", texto_completo) if len(f.strip()) > 25]
    if not frases:
        return [], []
    freq = Counter(palavras_relevantes(texto_completo))
    if not freq:
        return frases[:3], []
    alvo = max_frases or max(3, min(10, len(frases) // 8))
    pontuadas = []
    for i, f in enumerate(frases):
        ps = palavras_relevantes(f)
        if len(ps) < 4:
            continue
        pontuadas.append((sum(freq[p] for p in ps) / math.pow(len(ps), 0.6), i))
    escolhidas = sorted(i for _, i in sorted(pontuadas, reverse=True)[:alvo])
    resumo = [frases[i] for i in escolhidas]
    termos = [p for p, _ in freq.most_common(12) if len(p) >= 5][:8]
    return resumo, termos


GATILHOS_ACAO = re.compile(
    r"\b(entrega|entregar|entregue|prazo|prova|trabalho|tarefa|atividade|exerc[ií]cio|"
    r"projeto|checkpoint|sprint|reuni[aã]o|combinad[oa]|precisa|precisamos|n[aã]o esque[cç]a|"
    r"segunda|ter[cç]a|quarta|quinta|sexta|s[aá]bado|domingo|amanh[aã]|semana que vem|"
    r"pr[oó]xima (aula|semana)|at[eé] (dia|o dia)|\d{1,2}/\d{1,2})\b", re.IGNORECASE)


def extrair_acoes(texto_completo, limite=8):
    frases = [f.strip() for f in re.split(r"(?<=[.!?])\s+", texto_completo) if len(f.strip()) > 15]
    return [f for f in frases if GATILHOS_ACAO.search(f)][:limite]


def interpretar_com_ia(texto_completo):
    if not OLLAMA_ATIVO:
        return ""
    """Interpretação final usando Ollama local, sem custo por crédito."""
    if not texto_completo.strip():
        return "*Não houve texto suficiente para interpretar.*"
    chave = hashlib.sha256(texto_completo.encode("utf-8")).hexdigest()
    try:
        cache = json.loads(IA_CACHE.read_text(encoding="utf-8")) if IA_CACHE.exists() else {}
        if chave in cache:
            return cache[chave]
    except (OSError, ValueError):
        cache = {}
    prompt = f"""Você organiza transcrições em português do Brasil.
Responda em Markdown com as seções: Ideia central, Pontos importantes,
Tarefas e prazos, Dúvidas ou pontos a confirmar. Seja objetivo e não invente.

TRANSCRIÇÃO:\n{texto_completo}"""
    payload = json.dumps({"model": OLLAMA_MODELO, "prompt": prompt,
                          "stream": False, "options": {"temperature": 0.2}}).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=600) as resposta:
            resultado = json.loads(resposta.read().decode("utf-8"))
        interpretacao = str(resultado.get("response", "")).strip()
        if not interpretacao:
            raise RuntimeError("O Ollama não retornou texto.")
    except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError) as exc:
        return (f"*Interpretação IA indisponível. Inicie o Ollama e baixe "
                f"`{OLLAMA_MODELO}`. Detalhe: `{exc}`*")
    cache[chave] = interpretacao
    try:
        IA_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return interpretacao


def nome_unico(pasta, base):
    destino = pasta / f"{base}.md"
    n = 2
    while destino.exists():
        destino = pasta / f"{base}_{n}.md"
        n += 1
    return destino


def montar_nota(titulo, segmentos, duracao, idioma, modelo, pasta_destino, hoje=None, origem="de áudio"):
    hoje = hoje or datetime.now().strftime("%Y-%m-%d")
    paragrafos = agrupar_paragrafos(segmentos)
    texto_completo = " ".join(t for _, _, t in segmentos)
    resumo, termos = resumir(texto_completo)
    interpretacao_ia = interpretar_com_ia(texto_completo)

    tags = ["transcricao", "audio"] + (["ao-vivo"] if origem == "ao vivo" else [])
    for t in termos:
        s = slug_tag(t)
        if s and s not in tags and len(tags) < 6:
            tags.append(s)

    moc = pasta_destino
    linhas = [
        "---",
        "tipo: resumo",
        f"titulo: {titulo}",
        f"criado: {hoje}",
        f"tags: [{', '.join(tags)}]",
        "---",
        "",
        f"# {titulo}",
        "",
        f"> Transcrição automática {origem} · {hoje} · duração {fmt_tempo(duracao)} · "
        f"idioma `{idioma}` · modelo Whisper `{modelo}` (local, custo 0)",
        "",
        "## Resumo",
        "",
        "*Resumo extrativo gerado automaticamente: seleciona as frases mais representativas "
        "da fala, sem reescrever. Revise antes de confiar em detalhes.*",
        "",
    ]
    linhas += [f"- {f}" for f in resumo] or ["- *(áudio curto demais para resumir)*"]
    linhas += ["", "## Interpretação IA", "",
               "*Gerada localmente após o término do áudio. Revise informações importantes.*", "",
               interpretacao_ia]
    acoes = extrair_acoes(texto_completo)
    if acoes:
        linhas += ["", "## Ações e prazos", "",
                   "*Frases que citam entregas, datas, provas ou tarefas. Confira no áudio.*", ""]
        linhas += [f"- [ ] {a}" for a in acoes]
    if termos:
        linhas += ["", "## Termos frequentes", "", ", ".join(f"`{t}`" for t in termos)]
    linhas += ["", "## Transcrição completa", ""]
    linhas += [f"**[{fmt_tempo(ini)}]** {texto}\n" for ini, texto in paragrafos]
    linhas += ["---", "", "## Conexões", f"← [[{moc}]] | [[Hub_Central]]", ""]
    meta = {"resumo": resumo, "interpretacao_ia": interpretacao_ia,
            "acoes": acoes, "termos": termos, "tags": tags}
    return "\n".join(linhas), meta


def transcrever_trecho(audio, modelo="base", idioma="pt", contexto=""):
    """Tempo real: `audio` e um numpy float32 mono 16 kHz. Retorna [(inicio, fim, texto)]
    com tempos relativos ao trecho. `contexto` (fim do texto anterior) ajuda a manter o fio."""
    wm = carregar_modelo(modelo)
    lang = None if idioma in (None, "", "auto") else idioma
    gen, _ = wm.transcribe(audio, language=lang, vad_filter=True, beam_size=1,
                           condition_on_previous_text=False, initial_prompt=contexto or None)
    return [(s.start, s.end, s.text.strip()) for s in gen
            if s.text.strip() and s.no_speech_prob < 0.6]


def salvar_nota(titulo, segmentos, duracao, destino=DESTINO_PADRAO, modelo=MODELO_PADRAO,
                idioma="pt", origem="de áudio", vault=None):
    """Monta a nota .md no vault a partir de segmentos [(inicio, fim, texto)] ja transcritos."""
    vault = vault or VAULT
    if destino not in listar_destinos(vault):
        raise ValueError(f"Destino invalido: {destino}")
    titulo = re.sub(r"\s+", " ", titulo.replace(":", " -")).strip()[:120] or "Transcricao"
    if not segmentos:
        raise RuntimeError("Nenhuma fala detectada no áudio.")
    pasta = vault / destino
    hoje = datetime.now().strftime("%Y-%m-%d")
    arquivo = nome_unico(pasta, f"{pascal_case(titulo)}_{hoje.replace('-', '_')}")
    conteudo, meta = montar_nota(titulo, segmentos, duracao, idioma, modelo, destino, hoje, origem)
    arquivo.write_text(conteudo, encoding="utf-8")
    meta.update(titulo=titulo, criado=hoje, duracao=round(duracao), idioma=idioma, modelo=modelo)
    return arquivo, meta


def gerar_nota(caminho_audio, titulo, destino=DESTINO_PADRAO, modelo=MODELO_PADRAO,
               idioma="pt", progresso=None, vault=None):
    vault = vault or VAULT
    if destino not in listar_destinos(vault):
        raise ValueError(f"Destino invalido: {destino}")
    segmentos, duracao, idioma_det = transcrever(caminho_audio, modelo, idioma, progresso)
    return salvar_nota(titulo, segmentos, duracao, destino, modelo, idioma_det, vault=vault)


def main():
    ap = argparse.ArgumentParser(description="Transcreve audio e gera nota .md no vault")
    ap.add_argument("audio")
    ap.add_argument("--titulo", required=True)
    ap.add_argument("--destino", default=DESTINO_PADRAO, choices=listar_destinos())
    ap.add_argument("--modelo", default=MODELO_PADRAO, choices=MODELOS)
    ap.add_argument("--idioma", default="pt")
    a = ap.parse_args()
    arq, _ = gerar_nota(a.audio, a.titulo, a.destino, a.modelo, a.idioma,
                        lambda p: print(f"\r{p:.0%}", end="", flush=True))
    print(f"\n[OK] Nota criada: {arq.relative_to(VAULT)}")


if __name__ == "__main__":
    main()
