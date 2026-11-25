#!/usr/bin/env python3
"""
servidor_relay.py - ponte HTTP entre o navegador e o ESP8266 (Desafio 5).

Roda na VM da AWS, que tem IP publico. O ESP8266 fica em outra rede, atras
de NAT, e por isso so abre conexoes de SAIDA ate esta VM (long polling):

  1. O ESP8266 faz GET /esp/poll e a VM segura o pedido por ate 3 s.
  2. Quando um navegador pede uma pagina (ex.: GET /ligar), a VM entrega
     o caminho "/ligar" como resposta ao poll do ESP8266.
  3. O ESP8266 aciona a saida, gera a pagina e a devolve com
     POST /esp/reply?id=N.
  4. A VM entrega essa pagina ao navegador.

A pagina e sempre gerada pelo ESP8266; a VM so repassa os bytes.

Uso:
    RELAY_TOKEN=segredo RELAY_PORT=8080 python3 servidor_relay.py

Rotas:
    /esp/poll, /esp/reply  -> usadas so pelo ESP8266 (exigem o token)
    /_relay/status         -> estado da ponte em JSON
    qualquer outra         -> repassada ao ESP8266
"""

import itertools
import json
import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

PORTA = int(os.environ.get("RELAY_PORT", "8080"))
TOKEN = os.environ.get("RELAY_TOKEN", "troque-este-token")

ESPERA_POLL = 3.0        # segundos que a VM segura o GET /esp/poll
ESPERA_RESPOSTA = 10.0   # segundos que o navegador espera o ESP8266 responder
OFFLINE_APOS = 8.0       # sem contato ha mais tempo que isso = ESP8266 offline
MAX_FILA = 20            # pedidos de navegador esperando o ESP8266, no maximo

_cond = threading.Condition()
_fila = []               # (id, caminho) esperando o ESP8266 buscar
_respostas = {}          # id -> None (esperando) ou dict com a resposta
_ids = itertools.count(1)
_ultimo_contato = 0.0
_total_repassados = 0

HTML = "text/html; charset=utf-8"
TEXTO = "text/plain; charset=utf-8"


def log(msg):
    print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def esp_online():
    return time.time() - _ultimo_contato <= OFFLINE_APOS


def pagina_aviso(titulo, texto):
    """Pagina mostrada pela propria VM quando o ESP8266 nao responde."""
    return (
        "<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<meta http-equiv='refresh' content='5'>"
        "<title>" + titulo + "</title><style>"
        "body{font-family:Arial,Helvetica,sans-serif;background:#f2f4f7;margin:0;color:#1d2433}"
        "main{max-width:420px;margin:24px auto;background:#fff;border-radius:12px;"
        "padding:24px;box-shadow:0 1px 4px rgba(0,0,0,.12)}"
        "h1{font-size:22px;margin:0 0 12px}p{color:#4a5361}"
        "</style></head><body><main>"
        "<h1>" + titulo + "</h1><p>" + texto + "</p>"
        "<p>Esta mensagem vem da VM na AWS. A p&aacute;gina ser&aacute; "
        "recarregada a cada 5 segundos.</p></main></body></html>"
    )


class Ponte(BaseHTTPRequestHandler):
    server_version = "PonteESP8266/1.0"

    def log_message(self, fmt, *args):
        pass  # o log padrao e substituido pelas mensagens de log() abaixo

    # ---------- utilitarios ----------
    def _enviar(self, codigo, tipo, corpo):
        if isinstance(corpo, str):
            corpo = corpo.encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _sem_conteudo(self):
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    @staticmethod
    def _token_ok(qs):
        return qs.get("token", [""])[0] == TOKEN

    # ---------- rotas ----------
    def do_GET(self):
        url = urlsplit(self.path)
        qs = parse_qs(url.query)
        if url.path == "/esp/poll":
            self._poll(qs)
        elif url.path == "/_relay/status":
            self._status()
        elif url.path == "/favicon.ico":
            self._sem_conteudo()  # nao incomoda o ESP8266 com o icone
        elif url.path.startswith("/esp/"):
            self._enviar(404, TEXTO, "rota inexistente")
        else:
            self._repassar()

    def do_POST(self):
        url = urlsplit(self.path)
        if url.path == "/esp/reply":
            self._reply(parse_qs(url.query))
        else:
            self._enviar(405, TEXTO, "use GET")

    # ---------- lado do ESP8266 ----------
    def _poll(self, qs):
        global _ultimo_contato
        if not self._token_ok(qs):
            log("poll recusado: token errado vindo de %s" % self.client_address[0])
            self._enviar(403, TEXTO, "token invalido")
            return
        with _cond:
            if not esp_online():
                log("ESP8266 conectado (IP publico %s)" % self.client_address[0])
            _ultimo_contato = time.time()  # conta so a chegada do poll
            _cond.wait_for(lambda: len(_fila) > 0, timeout=ESPERA_POLL)
            item = _fila.pop(0) if _fila else None
        if item is None:
            self._sem_conteudo()  # nenhum pedido; o ESP8266 pergunta de novo
        else:
            rid, caminho = item
            self._enviar(200, TEXTO, "%d\n%s" % (rid, caminho))

    def _reply(self, qs):
        global _ultimo_contato
        if not self._token_ok(qs):
            self._enviar(403, TEXTO, "token invalido")
            return
        try:
            rid = int(qs.get("id", ["0"])[0])
            codigo = int(qs.get("code", ["200"])[0])
        except ValueError:
            self._enviar(400, TEXTO, "id ou code invalido")
            return
        tamanho = int(self.headers.get("Content-Length") or 0)
        corpo = self.rfile.read(tamanho) if tamanho > 0 else b""
        tipo = self.headers.get("Content-Type") or HTML
        with _cond:
            _ultimo_contato = time.time()
            esperando = rid in _respostas and _respostas[rid] is None
            if esperando:
                _respostas[rid] = {"codigo": codigo, "tipo": tipo, "corpo": corpo}
                _cond.notify_all()
        if esperando:
            self._enviar(200, TEXTO, "ok")
        else:
            self._enviar(410, TEXTO, "pedido expirado")

    # ---------- lado do navegador ----------
    def _repassar(self):
        global _total_repassados
        caminho = self.path  # inclui a query string, se houver
        cliente = self.client_address[0]
        if not esp_online():
            log("%s pediu %s, mas o ESP8266 esta offline" % (cliente, caminho))
            self._enviar(503, HTML, pagina_aviso(
                "ESP8266 offline",
                "O servidor na nuvem est&aacute; no ar, mas o ESP8266 n&atilde;o "
                "se conectou nos &uacute;ltimos %d segundos." % OFFLINE_APOS))
            return
        with _cond:
            if len(_fila) >= MAX_FILA:
                resposta = None
                cheia = True
            else:
                cheia = False
                rid = next(_ids)
                _respostas[rid] = None
                _fila.append((rid, caminho))
                _cond.notify_all()
                _cond.wait_for(lambda: _respostas.get(rid) is not None,
                               timeout=ESPERA_RESPOSTA)
                resposta = _respostas.pop(rid, None)
                if resposta is None:
                    # o ESP8266 nao respondeu a tempo: tira o pedido da fila
                    _fila[:] = [it for it in _fila if it[0] != rid]
                else:
                    _total_repassados += 1
        if cheia:
            self._enviar(503, HTML, pagina_aviso(
                "Muitos pedidos", "Aguarde alguns segundos e tente de novo."))
        elif resposta is None:
            log("%s pediu %s: o ESP8266 nao respondeu a tempo" % (cliente, caminho))
            self._enviar(504, HTML, pagina_aviso(
                "ESP8266 sem resposta",
                "O pedido chegou &agrave; nuvem, mas o ESP8266 n&atilde;o "
                "respondeu em %d segundos." % ESPERA_RESPOSTA))
        else:
            log("%s pediu %s -> %d (pagina gerada pelo ESP8266)"
                % (cliente, caminho, resposta["codigo"]))
            self._enviar(resposta["codigo"], resposta["tipo"], resposta["corpo"])

    def _status(self):
        with _cond:
            dados = {
                "esp_online": esp_online(),
                "ultimo_contato": (datetime.fromtimestamp(_ultimo_contato)
                                   .strftime("%Y-%m-%d %H:%M:%S")
                                   if _ultimo_contato else None),
                "pedidos_na_fila": len(_fila),
                "paginas_repassadas": _total_repassados,
            }
        self._enviar(200, "application/json; charset=utf-8",
                     json.dumps(dados, ensure_ascii=False, indent=2))


def main():
    servidor = ThreadingHTTPServer(("0.0.0.0", PORTA), Ponte)
    servidor.daemon_threads = True
    log("Ponte ESP8266 ouvindo na porta %d" % PORTA)
    if TOKEN == "troque-este-token":
        log("AVISO: usando o token padrao; defina a variavel RELAY_TOKEN")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        log("encerrando")


if __name__ == "__main__":
    main()
