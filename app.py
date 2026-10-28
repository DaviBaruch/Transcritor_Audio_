#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
app.py — interface web local do Transcritor de Audio (http://127.0.0.1:5055).

Roda so na sua maquina. Nada e enviado para a internet, exceto o download unico
do modelo Whisper na primeira vez que cada modelo e usado.

Rotas: / (interface), /login, /enviar, /status/<id>, /api/config, /api/historico,
       /api/item/<id> (GET e DELETE), /api/organizar/<id>, /api/auth, /api/entrar,
       /api/registrar, /api/sair
"""

import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, redirect, request, send_from_directory, session
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash

AQUI = Path(__file__).resolve().parent
load_dotenv(AQUI / ".env")
import transcritor as T
HISTORICO = AQUI / "historico.json"
MODO_PUBLICO = os.getenv("TRANSCRITOR_PUBLIC_MODE", "0") == "1"
USUARIOS_DADOS = Path(os.getenv("TRANSCRITOR_DATA_ROOT", str(AQUI / "dados_usuarios"))).resolve()

app = Flask(__name__, static_folder=str(AQUI / "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("TRANSCRITOR_MAX_UPLOAD_MB", "2048")) * 1024 * 1024
app.config["ALLOW_REGISTRATION"] = os.getenv("TRANSCRITOR_ALLOW_REGISTRATION", "0" if MODO_PUBLICO else "1") == "1"

EXTENSOES = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".webm", ".mp4", ".aac", ".wma", ".opus"}
JOBS = {}
AO_VIVO = {}
TRAVA_CPU = threading.Lock()
TRAVA_HIST = threading.Lock()


def usuario_atual():
    return str(session.get("u", "")).lower()


def vault_usuario():
    if MODO_PUBLICO:
        return USUARIOS_DADOS / usuario_atual().capitalize()
    return T.VAULT if usuario_atual() == "davibaruch" else USUARIOS_DADOS / usuario_atual().capitalize()


def historico_usuario():
    if MODO_PUBLICO or usuario_atual() != "davibaruch":
        return vault_usuario() / "historico.json"
    return HISTORICO


def oculta(nome):
    return nome.startswith(".") or nome == "__pycache__"


def dentro_de_repo(pasta):
    """True se a pasta (ou algum ancestral ate o vault) contem .git."""
    atual = pasta
    while True:
        if (atual / ".git").exists():
            return True
        if atual == vault_usuario() or atual.parent == atual:
            return False
        atual = atual.parent


def listar_pastas():
    """Pastas de destino permitidas: areas 00-09 (sem 07), sem ocultas e sem repos Git."""
    saida = []
    vault = vault_usuario()
    for area in T.listar_destinos(vault):
        raiz = vault / area
        for atual, subs, _ in os.walk(raiz):
            subs[:] = sorted(s for s in subs
                             if not oculta(s) and not (Path(atual) / s / ".git").exists())
            rel = Path(atual).relative_to(vault)
            if len(rel.parts) <= 4:
                saida.append(rel.as_posix())
            else:
                subs[:] = []
    return saida


def validar_destino(rel):
    vault = vault_usuario()
    destino = (vault / rel).resolve()
    try:
        partes = destino.relative_to(vault).parts
    except ValueError:
        raise ValueError("Destino fora do vault.")
    if not partes or partes[0] not in T.listar_destinos(vault):
        raise ValueError("Área de destino não permitida.")
    if any(oculta(p) for p in partes):
        raise ValueError("Pasta oculta não permitida.")
    if not destino.is_dir():
        raise ValueError("A pasta de destino não existe.")
    if dentro_de_repo(destino):
        raise ValueError("Pasta dentro de repositório Git: protegida.")
    return destino, partes


def ler_historico():
    historico = historico_usuario()
    if not historico.exists():
        return []
    try:
        return json.loads(historico.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def salvar_historico(itens):
    historico = historico_usuario()
    historico.parent.mkdir(parents=True, exist_ok=True)
    tmp = historico.with_suffix(".tmp")
    tmp.write_text(json.dumps(itens, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, historico)
    if not MODO_PUBLICO and usuario_atual() == "davibaruch":
        commit_historico()


def commit_historico():
    """Registra automaticamente alterações do histórico no Git local."""
    try:
        subprocess.run(
            ["git", "add", "--", HISTORICO.name],
            cwd=AQUI,
            check=True,
            capture_output=True,
            text=True,
        )
        alterado = subprocess.run(
            ["git", "diff", "--cached", "--quiet", "--", HISTORICO.name],
            cwd=AQUI,
            capture_output=True,
        )
        if alterado.returncode == 0:
            return
        subprocess.run(
            ["git", "commit", "-m", "Atualiza histórico de transcrições", "--", HISTORICO.name],
            cwd=AQUI,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        # O histórico já foi salvo; Git não pode derrubar a aplicação.
        print(f"Aviso: não foi possível fazer commit do histórico: {exc}")


def localizar(item, itens=None):
    """Acha o .md da transcricao; se foi movido fora daqui, procura pelo nome."""
    vault = vault_usuario()
    p = vault / item["arquivo"]
    if p.exists():
        return p
    nome = Path(item["arquivo"]).name
    for atual, subs, arquivos in os.walk(vault):
        subs[:] = [s for s in subs if not oculta(s) and not (Path(atual) / s / ".git").exists()]
        if nome in arquivos:
            achado = Path(atual) / nome
            item["arquivo"] = achado.relative_to(vault).as_posix()
            if itens is not None:
                salvar_historico(itens)
            return achado
    return None


def resumo_item(item, itens):
    p = localizar(item, itens)
    if p is None:
        estado, pasta = "ausente", ""
    else:
        pasta = p.parent.relative_to(vault_usuario()).as_posix()
        estado = "inbox" if pasta == "00_Inbox" else "organizada"
    return {"id": item["id"], "titulo": item["titulo"], "criado": item["criado"],
            "duracao": item["duracao"], "modelo": item["modelo"], "estado": estado,
            "pasta": pasta, "resumo": item.get("resumo", [])[:1]}


def extrair_transcricao(texto):
    m = re.search(r"^## Transcrição completa\s*$", texto, re.MULTILINE)
    if not m:
        return []
    resto = texto[m.end():]
    fim = re.search(r"^---\s*$", resto, re.MULTILINE)
    bloco = resto[:fim.start()] if fim else resto
    return [b.strip() for b in re.split(r"\n\s*\n", bloco) if b.strip()]


def ligar_no_moc(moc, stem, data):
    txt = moc.open("r", encoding="utf-8", newline="").read()
    if f"[[{stem}]]" in txt:
        return False
    sep = "\r\n" if "\r\n" in txt else "\n"
    linha = f"- [[{stem}]] — {data}"
    m = re.search(r"^## Transcrições[^\r\n]*$", txt, re.MULTILINE)
    if m:
        prox = re.search(r"^## ", txt[m.end():], re.MULTILINE)
        if prox:
            pos = m.end() + prox.start()
            novo = txt[:pos].rstrip("\r\n") + sep + linha + sep + sep + txt[pos:]
        else:
            novo = txt.rstrip("\r\n") + sep + linha + sep
    else:
        novo = txt.rstrip("\r\n") + sep + sep + "## Transcrições" + sep + sep + linha + sep
    moc.open("w", encoding="utf-8", newline="").write(novo)
    return True


PADRAO_CONEXAO = re.compile(r"^← \[\[[^\]]*\]\] \| \[\[Hub_Central\]\]", re.MULTILINE)


def extrair_interpretacao(texto):
    """Lê a seção gerada pela IA diretamente da nota Markdown."""
    marcador = "## Interpretação IA"
    if marcador not in texto:
        return ""
    parte = texto.split(marcador, 1)[1]
    return parte.split("\n## ", 1)[0].strip()


def processar(job_id, caminho, titulo, destino, modelo, idioma):
    job = JOBS[job_id]
    try:
        with TRAVA_CPU:
            job["estado"] = "processando"
            arq, meta = T.gerar_nota(caminho, titulo, destino, modelo, idioma,
                                     progresso=lambda p: job.__setitem__("progresso", p),
                                     vault=vault_usuario())
        item = {"id": job_id, "arquivo": arq.relative_to(vault_usuario()).as_posix(),
                "titulo": meta["titulo"], "criado": meta["criado"], "duracao": meta["duracao"],
                "modelo": meta["modelo"], "idioma": meta["idioma"], "resumo": meta["resumo"],
                "interpretacao_ia": meta.get("interpretacao_ia", ""),
                "acoes": meta["acoes"], "termos": meta["termos"], "tags": meta["tags"]}
        with TRAVA_HIST:
            itens = ler_historico()
            itens.append(item)
            salvar_historico(itens)
        job.update(estado="ok", progresso=1.0, item=job_id, arquivo=item["arquivo"])
    except Exception as exc:
        job.update(estado="erro", erro=str(exc))
    finally:
        try:
            os.remove(caminho)
        except OSError:
            pass


@app.get("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/config")
def config():
    return jsonify(destinos=T.listar_destinos(vault_usuario()), pastas=listar_pastas(), padrao=T.DESTINO_PADRAO,
                   modelo=T.MODELO_PADRAO)


@app.post("/api/pastas")
def criar_pasta():
    d = request.get_json(silent=True) or {}
    nome = str(d.get("nome", "")).strip()
    pai = str(d.get("pai", "")).strip()
    if not nome or len(nome) > 80 or any(c in nome for c in '\\/:*?"<>|') or nome in (".", ".."):
        return jsonify(erro="Nome de pasta invÃ¡lido."), 400
    vault = vault_usuario()
    try:
        base = vault if not pai else validar_destino(pai)[0]
        destino = (base / nome).resolve()
        destino.relative_to(vault)
        if any(oculta(p) for p in destino.relative_to(vault).parts):
            raise ValueError("Pasta oculta nÃ£o permitida.")
        if destino.exists():
            return jsonify(erro="Essa pasta jÃ¡ existe."), 409
        destino.mkdir()
    except (ValueError, OSError) as exc:
        return jsonify(erro=str(exc) or "NÃ£o foi possÃ­vel criar a pasta."), 400
    return jsonify(ok=True, pasta=destino.relative_to(vault).as_posix())


@app.post("/api/pastas/importar")
def importar_pastas():
    caminhos = (request.get_json(silent=True) or {}).get("caminhos", [])
    if not isinstance(caminhos, list) or len(caminhos) > 5000:
        return jsonify(erro="Estrutura de pastas inválida ou grande demais."), 400
    vault = vault_usuario()
    criadas = 0
    try:
        partes_unicas = set()
        for caminho in caminhos:
            partes = [p for p in str(caminho).replace("\\", "/").split("/") if p and p not in (".", "..")]
            for n in range(1, len(partes) + 1):
                partes_unicas.add(tuple(partes[:n]))
        for partes in sorted(partes_unicas, key=lambda p: (len(p), p)):
            if any(oculta(p) or any(c in p for c in '\\/:*?"<>|') for p in partes):
                continue
            destino = vault.joinpath(*partes).resolve()
            destino.relative_to(vault)
            if not destino.exists():
                destino.mkdir(parents=True)
                criadas += 1
    except (OSError, ValueError):
        return jsonify(erro="Não foi possível importar essa estrutura de pastas."), 400
    return jsonify(ok=True, criadas=criadas)


@app.post("/enviar")
def enviar():
    f = request.files.get("audio")
    if not f or not f.filename:
        return jsonify(erro="Nenhum áudio enviado."), 400
    ext = Path(f.filename).suffix.lower()
    if ext not in EXTENSOES:
        return jsonify(erro=f"Formato {ext or '?'} não suportado."), 400
    modelo = request.form.get("modelo", T.MODELO_PADRAO)
    destino = request.form.get("destino", T.DESTINO_PADRAO)
    if modelo not in T.MODELOS or destino not in listar_pastas():
        return jsonify(erro="Modelo ou destino inválido."), 400
    titulo = request.form.get("titulo", "").strip() or Path(f.filename).stem
    idioma = request.form.get("idioma", "pt")
    fd, caminho = tempfile.mkstemp(suffix=ext)
    os.close(fd)
    f.save(caminho)
    job_id = uuid.uuid4().hex[:10]
    JOBS[job_id] = {"estado": "fila", "progresso": 0.0}
    threading.Thread(target=processar, args=(job_id, caminho, titulo, destino, modelo, idioma),
                     daemon=True).start()
    return jsonify(id=job_id)


@app.get("/status/<job_id>")
def status(job_id):
    return jsonify(JOBS.get(job_id, {"estado": "erro", "erro": "Tarefa não encontrada.", "progresso": 0}))


# ---------------- transcrição ao vivo ----------------
@app.post("/api/ao-vivo/iniciar")
def ao_vivo_iniciar():
    d = request.get_json(silent=True) or {}
    modelo = str(d.get("modelo", "base"))
    destino = str(d.get("destino", T.DESTINO_PADRAO))
    idioma = str(d.get("idioma", "pt"))
    if modelo not in T.MODELOS or destino not in listar_pastas():
        return jsonify(erro="Modelo ou destino inválido."), 400
    sessao_id = uuid.uuid4().hex[:10]
    AO_VIVO[sessao_id] = {
        "titulo": str(d.get("titulo", "")).strip() or "Gravação ao vivo",
        "destino": destino, "modelo": modelo, "idioma": idioma,
        "segmentos": [], "duracao": 0.0, "contexto": ""
    }
    return jsonify(id=sessao_id)


@app.post("/api/ao-vivo/<sessao_id>/trecho")
def ao_vivo_trecho(sessao_id):
    sessao = AO_VIVO.get(sessao_id)
    if not sessao:
        return jsonify(erro="Sessão ao vivo não encontrada."), 404
    if request.mimetype != "application/octet-stream":
        return jsonify(erro="O trecho precisa ser PCM mono 16 kHz."), 400
    dados = request.get_data()
    if len(dados) < 4 or len(dados) % 2:
        return jsonify(segmentos=[])
    try:
        import numpy as np
        audio = np.frombuffer(dados, dtype="<i2").astype("float32") / 32768.0
        inicio = max(0.0, float(request.headers.get("X-Inicio", "0")))
        with TRAVA_CPU:
            trechos = T.transcrever_trecho(audio, sessao["modelo"], sessao["idioma"], sessao["contexto"])
    except Exception as exc:
        return jsonify(erro=f"Falha na transcrição ao vivo: {exc}"), 500

    resposta = []
    for ini, fim, texto in trechos:
        absoluto = (inicio + ini, inicio + fim, texto)
        sessao["segmentos"].append(absoluto)
        sessao["contexto"] = (sessao["contexto"] + " " + texto).strip()[-600:]
        resposta.append({"ini": absoluto[0], "fim": absoluto[1], "texto": texto})
    sessao["duracao"] = max(sessao["duracao"], inicio + (len(dados) / 2) / 16000)
    return jsonify(segmentos=resposta)


@app.post("/api/ao-vivo/<sessao_id>/finalizar")
def ao_vivo_finalizar(sessao_id):
    sessao = AO_VIVO.pop(sessao_id, None)
    if not sessao:
        return jsonify(erro="Sessão ao vivo não encontrada."), 404
    try:
        with TRAVA_CPU:
            arquivo, meta = T.salvar_nota(sessao["titulo"], sessao["segmentos"], sessao["duracao"],
                                          sessao["destino"], sessao["modelo"], sessao["idioma"], "ao vivo",
                                          vault=vault_usuario())
        item = {"id": uuid.uuid4().hex[:10], "arquivo": arquivo.relative_to(vault_usuario()).as_posix(),
                "titulo": meta["titulo"], "criado": meta["criado"], "duracao": meta["duracao"],
                "modelo": meta["modelo"], "idioma": meta["idioma"], "resumo": meta["resumo"],
                "interpretacao_ia": meta.get("interpretacao_ia", ""),
                "acoes": meta["acoes"], "termos": meta["termos"], "tags": meta["tags"]}
        with TRAVA_HIST:
            itens = ler_historico()
            itens.append(item)
            salvar_historico(itens)
        return jsonify(ok=True, id=item["id"], arquivo=item["arquivo"],
                       interpretacao_ia=item.get("interpretacao_ia", ""))
    except Exception as exc:
        return jsonify(erro=str(exc)), 500


@app.post("/api/ao-vivo/<sessao_id>/cancelar")
def ao_vivo_cancelar(sessao_id):
    AO_VIVO.pop(sessao_id, None)
    return jsonify(ok=True)


@app.get("/api/historico")
def historico():
    with TRAVA_HIST:
        itens = ler_historico()
        lista = [resumo_item(i, itens) for i in reversed(itens)]
    return jsonify(lista)


@app.get("/api/item/<item_id>")
def item_detalhe(item_id):
    with TRAVA_HIST:
        itens = ler_historico()
        item = next((i for i in itens if i["id"] == item_id), None)
        if not item:
            return jsonify(erro="Item não encontrado."), 404
        base = resumo_item(item, itens)
        p = localizar(item, itens)
    texto = p.read_text(encoding="utf-8", errors="ignore") if p else ""
    base.update(acoes=item.get("acoes", []), termos=item.get("termos", []),
                resumo=item.get("resumo", []), idioma=item.get("idioma", ""),
                interpretacao_ia=item.get("interpretacao_ia") or extrair_interpretacao(texto),
                arquivo=item["arquivo"], transcricao=extrair_transcricao(texto))
    return jsonify(base)


@app.post("/api/organizar/<item_id>")
def organizar(item_id):
    rel = (request.get_json(silent=True) or {}).get("pasta", "")
    try:
        destino, partes = validar_destino(rel)
    except ValueError as exc:
        return jsonify(erro=str(exc)), 400
    with TRAVA_HIST:
        itens = ler_historico()
        item = next((i for i in itens if i["id"] == item_id), None)
        if not item:
            return jsonify(erro="Item não encontrado."), 404
        src = localizar(item, itens)
        if src is None:
            return jsonify(erro="O arquivo da nota não foi encontrado no vault."), 404
        if src.parent == destino:
            return jsonify(erro="A nota já está nessa pasta."), 400
        dst = T.nome_unico(destino, src.stem)
        shutil.move(str(src), str(dst))
        item["arquivo"] = dst.relative_to(vault_usuario()).as_posix()
        salvar_historico(itens)

    area = partes[0]
    texto = dst.open("r", encoding="utf-8", newline="").read()
    novo = PADRAO_CONEXAO.sub(f"← [[{area}]] | [[Hub_Central]]", texto, count=1)
    if novo != texto:
        dst.open("w", encoding="utf-8", newline="").write(novo)

    ligado = False
    moc = vault_usuario() / area / f"{area}.md"
    if area != "00_Inbox" and moc.exists():
        ligado = ligar_no_moc(moc, dst.stem, item["criado"])
    return jsonify(ok=True, arquivo=item["arquivo"], moc=area if ligado else None,
                   aviso=None if (ligado or area == "00_Inbox")
                   else "Nota movida, mas o índice da área não foi alterado (não existe ou já continha o link).")

# ---------------- login (usuario local) ----------------
USUARIOS = (USUARIOS_DADOS / "usuarios.json") if MODO_PUBLICO else (AQUI / "usuarios.json")
CHAVE = Path.home() / ".config" / "Transcritor_Audio" / ".chave_sessao"  # fora do repo, seguro
NOME_OK = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
FALHAS = {}                            # ip -> [erros seguidos, bloqueado_ate]
LIVRES = {"static", "pagina_login", "auth_estado", "auth_registrar", "auth_entrar"}


def chave_secreta():
    definida = os.getenv("TRANSCRITOR_SECRET_KEY", "").strip()
    if definida:
        return definida
    CHAVE.parent.mkdir(parents=True, exist_ok=True)
    try:
        return CHAVE.read_text(encoding="utf-8").strip()
    except OSError:
        # migra a chave antiga (dentro do repo) para o local seguro, se existir
        antiga = AQUI / ".chave_sessao"
        try:
            k = antiga.read_text(encoding="utf-8").strip()
        except OSError:
            k = secrets.token_hex(32)
        CHAVE.write_text(k, encoding="utf-8")
        return k


app.secret_key = chave_secreta()
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_SECURE=os.getenv("TRANSCRITOR_COOKIE_SECURE", "0") == "1",
                  PERMANENT_SESSION_LIFETIME=timedelta(days=30))


@app.after_request
def cabecalhos_seguranca(resposta):
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    resposta.headers.setdefault("Referrer-Policy", "same-origin")
    resposta.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(), payment=()")
    if request.is_secure:
        resposta.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return resposta


def ler_usuarios():
    if MODO_PUBLICO and not USUARIOS.exists():
        legado = AQUI / "usuarios.json"
        try:
            if legado.exists():
                return json.loads(legado.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    try:
        return json.loads(USUARIOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def salvar_usuarios(u):
    USUARIOS.parent.mkdir(parents=True, exist_ok=True)
    tmp = USUARIOS.with_suffix(".tmp")
    tmp.write_text(json.dumps(u, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, USUARIOS)


def perfil_usuario():
    p = vault_usuario() / "perfil.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"tema": "aurora", "foto": ""}


def salvar_perfil(dados):
    p = vault_usuario() / "perfil.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")


def abrir_sessao(chave, lembrar):
    session.clear()
    session["u"] = chave
    session.permanent = bool(lembrar)


@app.before_request
def exigir_login():
    if request.endpoint in LIVRES or session.get("u") in ler_usuarios():
        return None
    if request.path.startswith(("/api/", "/status/", "/enviar")):
        return jsonify(erro="Não autenticado."), 401
    return redirect("/login")


@app.get("/login")
def pagina_login():
    return send_from_directory(app.static_folder, "login.html")


@app.get("/api/auth")
def auth_estado():
    us = ler_usuarios()
    u = session.get("u")
    ok = u in us
    return jsonify(logado=ok, usuario=us[u]["nome"] if ok else None,
                   primeiro_acesso=not us, cadastro_aberto=app.config["ALLOW_REGISTRATION"])


@app.post("/api/registrar")
def auth_registrar():
    if not app.config["ALLOW_REGISTRATION"]:
        return jsonify(erro="O cadastro de novos usuários está desativado."), 403
    d = request.get_json(silent=True) or {}
    nome, senha = str(d.get("usuario", "")).strip(), str(d.get("senha", ""))
    if not NOME_OK.match(nome):
        return jsonify(erro="Usuário: 3 a 32 caracteres (letras, números, . _ -)."), 400
    if not 8 <= len(senha) <= 128:
        return jsonify(erro="A senha precisa ter pelo menos 8 caracteres."), 400
    us = ler_usuarios()
    chave = nome.lower()
    if chave in us:
        return jsonify(erro="Esse usuário já existe."), 409
    us[chave] = {"nome": nome, "hash": generate_password_hash(senha),
                 "criado": datetime.now().strftime("%Y-%m-%d")}
    salvar_usuarios(us)
    (USUARIOS_DADOS / nome.capitalize() / "00_Inbox").mkdir(parents=True, exist_ok=True)
    abrir_sessao(chave, d.get("lembrar"))
    return jsonify(ok=True)


@app.post("/api/entrar")
def auth_entrar():
    ip = request.remote_addr or "?"
    erros, ate = FALHAS.get(ip, [0, 0])
    if time.time() < ate:
        return jsonify(erro=f"Muitas tentativas. Aguarde {int(ate - time.time()) + 1} s."), 429
    d = request.get_json(silent=True) or {}
    chave = str(d.get("usuario", "")).strip().lower()
    reg = ler_usuarios().get(chave)
    if not reg or not check_password_hash(reg["hash"], str(d.get("senha", ""))):
        erros += 1
        FALHAS[ip] = [0, time.time() + 60] if erros >= 5 else [erros, 0]
        return jsonify(erro="Usuário ou senha incorretos."), 401
    FALHAS.pop(ip, None)
    (USUARIOS_DADOS / reg["nome"].capitalize() / "00_Inbox").mkdir(parents=True, exist_ok=True)
    abrir_sessao(chave, d.get("lembrar"))
    return jsonify(ok=True)


@app.post("/api/sair")
def auth_sair():
    session.clear()
    return jsonify(ok=True)


@app.get("/api/perfil")
def obter_perfil():
    us = ler_usuarios().get(usuario_atual(), {})
    p = perfil_usuario()
    return jsonify(usuario=us.get("nome", usuario_atual()), tema=p.get("tema", "aurora"), foto=p.get("foto", ""))


@app.post("/api/perfil")
def atualizar_perfil():
    d = request.get_json(silent=True) or {}
    tema = str(d.get("tema", "aurora"))
    foto = str(d.get("foto", ""))
    if tema not in {"aurora", "oceano", "grafite", "floresta", "neon", "papel"}:
        return jsonify(erro="Tema inválido."), 400
    if len(foto) > 700_000 or (foto and not foto.startswith("data:image/")):
        return jsonify(erro="Imagem de perfil inválida."), 400
    salvar_perfil({"tema": tema, "foto": foto})
    return jsonify(ok=True, tema=tema, foto=foto)


# ---------------- excluir transcricao ----------------
def desligar_do_moc(moc, stem):
    """Remove do indice da area a linha '- [[stem]] ...' que o organizar() criou."""
    txt = moc.open("r", encoding="utf-8", newline="").read()
    padrao = re.compile(r"^\s*-\s*\[\[" + re.escape(stem) + r"(\|[^\]]*)?\]\]")
    linhas = txt.splitlines(keepends=True)
    novas = [l for l in linhas if not padrao.match(l)]
    if len(novas) == len(linhas):
        return False
    moc.open("w", encoding="utf-8", newline="").write("".join(novas))
    return True


@app.delete("/api/item/<item_id>")
def excluir(item_id):
    apagar_nota = bool((request.get_json(silent=True) or {}).get("nota"))
    aviso, moc_limpo, nota_movida = None, False, False
    with TRAVA_HIST:
        itens = ler_historico()
        item = next((i for i in itens if i["id"] == item_id), None)
        if not item:
            return jsonify(erro="Item não encontrado."), 404
        ids = {item["id"]}
        if apagar_nota:
            src = localizar(item, itens)
            if src is None:
                aviso = "A nota já não existia no vault; removi só do histórico."
            elif dentro_de_repo(src.parent):
                return jsonify(erro="A nota está dentro de um repositório Git (protegida). Remova só do histórico."), 400
            else:
                lixeira = vault_usuario() / ".trash"      # lixeira local restauravel
                try:
                    lixeira.mkdir(exist_ok=True)
                    shutil.move(str(src), str(T.nome_unico(lixeira, src.stem)))
                except OSError as exc:
                    return jsonify(erro=f"Não consegui mover a nota: {exc}"), 500
                nota_movida = True
                area = src.relative_to(vault_usuario()).parts[0]
                moc = vault_usuario() / area / f"{area}.md"
                if area != "00_Inbox" and moc.exists():
                    moc_limpo = desligar_do_moc(moc, src.stem)
                # outras entradas do historico que apontavam para a mesma nota
                ids |= {i["id"] for i in itens if i["arquivo"] == item["arquivo"]}
        salvar_historico([i for i in itens if i["id"] not in ids])
    return jsonify(ok=True, nota=nota_movida, moc=moc_limpo, removidos=len(ids), aviso=aviso)


if __name__ == "__main__":
    host = os.getenv("TRANSCRITOR_HOST", "127.0.0.1")
    porta = int(os.getenv("TRANSCRITOR_PORT", "5055"))
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{porta}")).start()
    app.run(host=host, port=porta, debug=False)
