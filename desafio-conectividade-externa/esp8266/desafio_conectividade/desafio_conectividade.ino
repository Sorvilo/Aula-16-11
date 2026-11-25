/*
  desafio_conectividade.ino
  Desafio 5 - Conectividade externa com ESP8266
  Disciplina Machine to Machine e IoT - Leonardo Sorvilo

  O ESP8266 hospeda uma pagina web que liga e desliga uma carga (LED ou rele).
  A pagina pode ser aberta de dois jeitos:

    1. Direto na rede local: http://<IP local do ESP8266>/
    2. De qualquer rede, pela VM na AWS: http://<IP publico da VM>:8080/
       O ESP8266 fica atras do NAT do roteador, entao ele mesmo abre a
       conexao ate a VM (GET /esp/poll), recebe o caminho pedido pelo
       navegador, gera a pagina e devolve (POST /esp/reply).

  Placa: NodeMCU 1.0 (ESP-12E) ou outro ESP8266.
  Monitor serial: 115200 baud.
*/

#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <ESP8266HTTPClient.h>

// ================== CONFIGURAR ANTES DE GRAVAR ==================
const char* WIFI_SSID  = "NOME_DA_REDE";
const char* WIFI_SENHA = "SENHA_DA_REDE";

// VM na AWS: IP publico, porta e token do servidor_relay.py
const char* SERVIDOR_HOST = "IP_PUBLICO_DA_VM";
const uint16_t SERVIDOR_PORTA = 8080;
const char* TOKEN = "TOKEN_DA_PONTE";

// Saida que aciona a carga. GPIO5 = pino D1 da NodeMCU (entrada IN do rele).
const uint8_t PINO_CARGA = 5;
// Troque para true se o seu modulo rele ligar quando a pagina diz DESLIGADA.
const bool CARGA_ATIVA_EM_LOW = false;
// O LED azul da placa (LED_BUILTIN) acompanha a carga, para teste sem rele.
// ================================================================

ESP8266WebServer servidorLocal(80);
WiFiClient clienteTcp;

bool cargaLigada = false;
unsigned long acionamentos = 0;
unsigned long proximaConsulta = 0;
bool ponteConectada = false;

struct Resposta {
  int codigo;
  const char* tipo;
  String corpo;
};

// ---------- carga ----------
void aplicarSaidas() {
  bool nivelAlto = CARGA_ATIVA_EM_LOW ? !cargaLigada : cargaLigada;
  digitalWrite(PINO_CARGA, nivelAlto ? HIGH : LOW);
  digitalWrite(LED_BUILTIN, cargaLigada ? LOW : HIGH);  // LED da placa acende com LOW
}

void mudarCarga(bool ligar) {
  if (ligar != cargaLigada) {
    acionamentos++;
  }
  cargaLigada = ligar;
  aplicarSaidas();
  Serial.printf("[CARGA] %s\n", cargaLigada ? "LIGADA" : "DESLIGADA");
}

// ---------- pagina ----------
String tempoLigado() {
  unsigned long s = millis() / 1000;
  char texto[16];
  snprintf(texto, sizeof(texto), "%02lu:%02lu:%02lu", s / 3600, (s / 60) % 60, s % 60);
  return String(texto);
}

String gerarPagina(bool viaInternet) {
  String h;
  h.reserve(3200);
  h += F("<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'>"
         "<meta name='viewport' content='width=device-width,initial-scale=1'>"
         "<title>ESP8266 - Desafio 5</title><style>"
         "body{font-family:Arial,Helvetica,sans-serif;background:#f2f4f7;margin:0;color:#1d2433}"
         "main{max-width:420px;margin:24px auto;background:#fff;border-radius:12px;padding:24px;"
         "box-shadow:0 1px 4px rgba(0,0,0,.12)}"
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
         ".rodape{color:#8a93a0;font-size:12px;margin-top:16px;text-align:center}"
         "</style></head><body><main>"
         "<h1>Controle remoto - ESP8266</h1>"
         "<p class='sub'>P&aacute;gina gerada pelo ESP8266</p>");
  h += cargaLigada ? F("<div class='estado on'>L&Acirc;MPADA LIGADA</div>")
                   : F("<div class='estado off'>L&Acirc;MPADA DESLIGADA</div>");
  h += F("<div class='botoes'><a class='b ligar' href='/ligar'>Ligar</a>"
         "<a class='b desligar' href='/desligar'>Desligar</a></div><table>"
         "<tr><td>Acesso</td><td>");
  h += viaInternet ? F("pela internet (VM AWS)") : F("direto na rede local");
  h += F("</td></tr><tr><td>IP local do ESP8266</td><td>");
  h += WiFi.localIP().toString();
  h += F("</td></tr><tr><td>ID do chip</td><td>");
  h += String(ESP.getChipId(), HEX);
  h += F("</td></tr><tr><td>Sinal Wi-Fi</td><td>");
  h += String(WiFi.RSSI());
  h += F(" dBm</td></tr><tr><td>Ligado h&aacute;</td><td>");
  h += tempoLigado();
  h += F("</td></tr><tr><td>Acionamentos</td><td>");
  h += String(acionamentos);
  h += F("</td></tr></table>"
         "<p class='rodape'>Leonardo Sorvilo &middot; Machine to Machine e IoT &middot; "
         "<a href='/'>atualizar</a></p></main>"
         "<script>history.replaceState(null,'','/')</script></body></html>");
  return h;
}

// Trata um pedido, venha ele da rede local ou da VM
Resposta processar(String caminho, bool viaInternet) {
  int q = caminho.indexOf('?');
  if (q >= 0) {
    caminho = caminho.substring(0, q);
  }
  Serial.printf("[PEDIDO] %s %s\n", viaInternet ? "internet" : "local", caminho.c_str());

  if (caminho == "/ligar") {
    mudarCarga(true);
  } else if (caminho == "/desligar") {
    mudarCarga(false);
  } else if (caminho == "/alternar") {
    mudarCarga(!cargaLigada);
  } else if (caminho == "/estado") {
    String json = String("{\"ligada\":") + (cargaLigada ? "true" : "false") +
                  ",\"acionamentos\":" + acionamentos + "}";
    return {200, "application/json", json};
  } else if (caminho != "/") {
    return {404, "text/plain; charset=utf-8", "Pagina nao encontrada"};
  }
  return {200, "text/html; charset=utf-8", gerarPagina(viaInternet)};
}

// ---------- acesso local (mesma rede) ----------
void atenderLocal() {
  Resposta r = processar(servidorLocal.uri(), false);
  servidorLocal.send(r.codigo, r.tipo, r.corpo);
}

// ---------- acesso externo (ponte na VM) ----------
String enderecoPonte() {
  return String("http://") + SERVIDOR_HOST + ":" + SERVIDOR_PORTA;
}

void consultarPonte() {
  if ((long)(millis() - proximaConsulta) < 0) {
    return;  // esperando para tentar de novo depois de uma falha
  }

  HTTPClient http;
  http.setTimeout(8000);
  if (!http.begin(clienteTcp, enderecoPonte() + "/esp/poll?token=" + TOKEN)) {
    Serial.println("[PONTE] endereco invalido");
    proximaConsulta = millis() + 3000;
    return;
  }
  int codigo = http.GET();

  if (codigo == 204 || codigo == 200) {
    if (!ponteConectada) {
      Serial.println("[PONTE] conectado ao servidor na AWS");
      ponteConectada = true;
    }
  } else {
    if (codigo < 0) {
      Serial.printf("[PONTE] falha: %s\n", http.errorToString(codigo).c_str());
    } else {
      Serial.printf("[PONTE] servidor respondeu %d (token certo?)\n", codigo);
    }
    http.end();
    ponteConectada = false;
    proximaConsulta = millis() + 3000;
    return;
  }

  if (codigo == 204) {
    http.end();  // nenhum pedido; consulta de novo no proximo loop
    return;
  }

  String pedido = http.getString();
  http.end();
  int quebra = pedido.indexOf('\n');
  if (quebra < 0) {
    return;
  }
  String id = pedido.substring(0, quebra);
  String caminho = pedido.substring(quebra + 1);

  Resposta r = processar(caminho, true);

  HTTPClient envio;
  envio.setTimeout(8000);
  envio.begin(clienteTcp, enderecoPonte() + "/esp/reply?token=" + TOKEN +
                          "&id=" + id + "&code=" + r.codigo);
  envio.addHeader("Content-Type", r.tipo);
  int codigoEnvio = envio.POST(r.corpo);
  if (codigoEnvio != 200) {
    Serial.printf("[PONTE] resposta nao entregue (codigo %d)\n", codigoEnvio);
  }
  envio.end();
}

// ---------- inicializacao ----------
void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println("\n--- Desafio 5: conectividade externa ---");

  pinMode(PINO_CARGA, OUTPUT);
  pinMode(LED_BUILTIN, OUTPUT);
  aplicarSaidas();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_SENHA);
  Serial.print("Conectando ao Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("[WIFI] conectado. IP local: http://");
  Serial.println(WiFi.localIP());
  Serial.print("[PONTE] acesso externo: ");
  Serial.println(enderecoPonte() + "/");

  servidorLocal.onNotFound(atenderLocal);
  servidorLocal.begin();
  Serial.println("[LOCAL] servidor web na porta 80");
}

void loop() {
  servidorLocal.handleClient();
  if (WiFi.status() == WL_CONNECTED) {
    consultarPonte();
  }
}
