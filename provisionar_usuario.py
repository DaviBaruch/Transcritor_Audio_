"""Cria uma conta sem colocar a senha na linha de comando ou no repositório."""

import getpass
import re
import sys
from datetime import datetime

from werkzeug.security import generate_password_hash

import app


if len(sys.argv) != 2 or not re.fullmatch(r"[A-Za-z0-9._-]{3,32}", sys.argv[1]):
    raise SystemExit("Uso: python provisionar_usuario.py NOME_USUARIO")

nome = sys.argv[1]
senha = getpass.getpass("Senha: ")
confirmacao = getpass.getpass("Confirme a senha: ")
if len(senha) < 8 or senha != confirmacao:
    raise SystemExit("Senha inválida ou diferente da confirmação.")

usuarios = app.ler_usuarios()
chave = nome.lower()
if chave in usuarios:
    raise SystemExit("Esse usuário já existe.")
usuarios[chave] = {"nome": nome, "hash": generate_password_hash(senha),
                   "criado": datetime.now().strftime("%Y-%m-%d")}
app.salvar_usuarios(usuarios)
(app.USUARIOS_DADOS / nome.capitalize() / "00_Inbox").mkdir(parents=True, exist_ok=True)
print(f"Usuário {nome} criado.")
