#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <ESP8266HTTPClient.h>  // cliente HTTP (linha alterada pela VM AWS)

// --- Credenciais e Configurações de Rede ---
const char* WIFI_SSID = "Convidado iot";
const char* WIFI_PASS = "SUA_SENHA";  // coloque a senha do Wi-Fi antes de gravar na placa
const char* TARGET_NODE_IP = "192.168.4.3";
const uint16_t HTTP_PORT = 80;

// Constante para o intervalo de retransmissão
const unsigned long RETRANSMIT_DELAY_MS = 2000;

// --- Instância do Servidor ---
ESP8266WebServer webServer(HTTP_PORT);

// --- Variáveis de Estado de Controle ---
struct RelayControl {
  bool pending = false;
  unsigned long timestamp = 0;
  int payload = 0;
} relayState;

// --- Manipulador do Endpoint de Entrada ---
void handleRelayRoute() {
  if (!webServer.hasArg("valor")) {
    webServer.send(400, "text/plain", "Bad Request: Parametro 'valor' ausente");
    return;
  }

  int currentVal = webServer.arg("valor").toInt();
  relayState.payload = currentVal + 1;
  relayState.timestamp = millis();
  relayState.pending = true;

  Serial.printf("[INCOMING] Valor recebido: %d | Próximo a enviar: %d\n", currentVal,
                relayState.payload);

  webServer.send(200, "text/plain", "Processado: incremento agendado");
}

// --- Encaminhamento HTTP Assíncrono ---
void processPendingForward() {
  if (!relayState.pending) {
    return;
  }

  // Verifica se o tempo decorrido atingiu a janela programada
  if (millis() - relayState.timestamp >= RETRANSMIT_DELAY_MS) {
    relayState.pending = false;

    WiFiClient netClient;
    HTTPClient httpClient;

    String endpointUrl = String("http://") + TARGET_NODE_IP + "/relay?valor=" +
                         String(relayState.payload);

    Serial.println(String("[OUTGOING] Despachando pacote para: ") + endpointUrl);

    if (httpClient.begin(netClient, endpointUrl)) {
      int httpResponseCode = httpClient.GET();

      if (httpResponseCode > 0) {
        Serial.printf("[HTTP] Sucesso! Código de resposta: %d\n", httpResponseCode);
      } else {
        Serial.printf("[HTTP] Falha na comunicação: %s\n",
                      httpClient.errorToString(httpResponseCode).c_str());
      }

      httpClient.end();
    } else {
      Serial.println("[ERROR] Não foi possível inicializar a conexão HTTP");
    }
  }
}

// --- Inicialização ---
void setup() {
  Serial.begin(115200);
  delay(100);

  Serial.println("\n--- Inicializando Sistema M2M ---");
  Serial.print("Estabelecendo conexão Wi-Fi");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println("\n[STATUS] Conectado à rede com sucesso!");
  Serial.print("[INFO] Endereço IP local: ");
  Serial.println(WiFi.localIP());

  // Registro de rotas da API
  webServer.on("/relay", HTTP_GET, handleRelayRoute);
  webServer.begin();

  Serial.println("[STATUS] Servidor HTTP operacional e escutando requisições.");
}

// --- Ciclo Principal ---
void loop() {
  webServer.handleClient();
  processPendingForward();
}
