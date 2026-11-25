#!/usr/bin/env python3
"""
simulador_esp.py - faz o papel do ESP8266 para testar a ponte sem a placa.

Ele conversa com o servidor_relay.py exatamente como o sketch do ESP8266:
GET /esp/poll para buscar pedidos e POST /esp/reply para devolver a pagina.
A pagina gerada avisa em destaque que e um SIMULADOR, para nao ser
confundida com a evidencia do ESP8266 real.

Uso:
    python3 simulador_esp.py http://127.0.0.1:8080 SEU_TOKEN

Pare com Ctrl+C antes de ligar o ESP8266 real (os dois nao podem rodar juntos).
"""

import sys
import time
import urllib.error
import urllib.request

if len(sys.argv) != 3:
    print(__doc__)
    sys.exit(1)

SERVIDOR = sys.argv[1].rstrip("/")
TOKEN = sys.argv[2]
INICIO = time.time()
estado = {"ligada": False, "acionamentos": 0}


def mudar(ligar):
    if ligar != estado["ligada"]:
        estado["acionamentos"] += 1
    estado["ligada"] = ligar
    print("[CARGA]", "LIGADA" if ligar else "DESLIGADA", flush=True)


def pagina():
    s = int(time.time() - INICIO)
    ligada = estado["ligada"]
    return (
        "<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>SIMULADOR - Desafio 5</title><style>"
        "body{font-family:Arial,Helvetica,sans-serif;background:#f2f4f7;margin:0;color:#1d2433}"
        "main{max-width:420px;margin:24px auto;background:#fff;border-radius:12px;padding:24px;"
        "box-shadow:0 1px 4px rgba(0,0,0,.12)}"
        ".aviso{background:#7a1f1f;color:#fff;text-align:center;font-weight:bold;padding:8px;"
        "border-radius:8px;margin-bottom:16px}"
        "h1{font-size:22px;margin:0 0 4px}.sub{color:#5b6472;margin:0 0 20px;font-size:14px}"
        ".estado{text-align:center;font-size:20px;font-weight:bold;padding:18px;border-radius:10px;"
        "margin-bottom:16px}"
        ".on{background:#fff4c2;color:#7a5b00;border:2px solid #f0c000}"
        ".off{background:#e9ecf1;color:#4a5361;border:2px solid #c5cbd5}"
        ".botoes{display:flex;gap:12px;margin-bottom:20px}"
        ".b{flex:1;text-align:center;padding:14px;border-radius:8px;font-size:18px;font-weight:bold;"
        "text-decoration:none;color:#fff}.ligar{background:#1a7f37}.desligar{background:#b42318}"
        "table{width:100%;border-collapse:collapse;font-size:14px}"
        "td{padding:6px 0;border-bottom:1px solid #eceff3}td:last-child{text-align:right;font-weight:bold}"
        "</style></head><body><main>"
        "<div class='aviso'>SIMULADOR &ndash; teste sem o ESP8266</div>"
        "<h1>Controle remoto - ESP8266</h1>"
        "<p class='sub'>P&aacute;gina gerada pelo simulador, no lugar do ESP8266</p>"
        + ("<div class='estado on'>LÂMPADA LIGADA</div>" if ligada
           else "<div class='estado off'>LÂMPADA DESLIGADA</div>")
        + "<div class='botoes'><a class='b ligar' href='/ligar'>Ligar</a>"
        "<a class='b desligar' href='/desligar'>Desligar</a></div><table>"
        "<tr><td>Acesso</td><td>pela internet (VM AWS)</td></tr>"
        "<tr><td>Ligado h&aacute;</td><td>%02d:%02d:%02d</td></tr>"
        "<tr><td>Acionamentos</td><td>%d</td></tr></table>"
        "<script>history.replaceState(null,'','/')</script></main></body></html>"
        % (s // 3600, (s // 60) % 60, s % 60, estado["acionamentos"])
    )


def processar(caminho):
    caminho = caminho.split("?", 1)[0]
    print("[PEDIDO] internet", caminho, flush=True)
    if caminho == "/ligar":
        mudar(True)
    elif caminho == "/desligar":
        mudar(False)
    elif caminho == "/alternar":
        mudar(not estado["ligada"])
    elif caminho == "/estado":
        corpo = '{"ligada":%s,"acionamentos":%d}' % (
            "true" if estado["ligada"] else "false", estado["acionamentos"])
        return 200, "application/json", corpo
    elif caminho != "/":
        return 404, "text/plain; charset=utf-8", "Pagina nao encontrada"
    return 200, "text/html; charset=utf-8", pagina()


def main():
    print("Simulador ligado em", SERVIDOR, "(Ctrl+C para parar)", flush=True)
    conectado = False
    while True:
        try:
            with urllib.request.urlopen(
                    "%s/esp/poll?token=%s" % (SERVIDOR, TOKEN), timeout=8) as r:
                status = r.status
                corpo = r.read().decode("utf-8")
            if not conectado:
                print("[PONTE] conectado ao servidor", flush=True)
                conectado = True
            if status == 204:
                continue  # nenhum pedido; pergunta de novo
            rid, caminho = corpo.split("\n", 1)
            codigo, tipo, pagina_gerada = processar(caminho)
            pedido = urllib.request.Request(
                "%s/esp/reply?token=%s&id=%s&code=%d" % (SERVIDOR, TOKEN, rid, codigo),
                data=pagina_gerada.encode("utf-8"),
                headers={"Content-Type": tipo}, method="POST")
            with urllib.request.urlopen(pedido, timeout=8) as r:
                r.read()
        except KeyboardInterrupt:
            print("\nSimulador parado.")
            return
        except urllib.error.HTTPError as e:
            print("[PONTE] erro HTTP", e.code, flush=True)
            conectado = False
            time.sleep(3)
        except Exception as e:  # servidor fora do ar, rede caiu etc.
            print("[PONTE] falha:", e, flush=True)
            conectado = False
            time.sleep(3)


if __name__ == "__main__":
    main()
