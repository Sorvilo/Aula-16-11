# Desafio 5 – Conectividade externa com ESP8266

Página web hospedada no ESP8266, acessível de qualquer rede pela VM na AWS.

```
Navegador (4G ou outra rede) ──HTTP :8080──> VM na AWS <──GET /esp/poll── ESP8266 (atrás do NAT)
                                                       ──POST /esp/reply─>
```

O ESP8266 só abre conexões de **saída** até a VM (long polling), então funciona
atrás de NAT e CGNAT, sem mexer no roteador. A VM só repassa: quem gera a página
é o ESP8266.

## Arquivos

| Arquivo | Onde roda | Para quê |
| --- | --- | --- |
| `esp8266/desafio_conectividade/desafio_conectividade.ino` | ESP8266 | Página web, controle da carga e conexão com a ponte |
| `vm/servidor_relay.py` | VM AWS | Ponte HTTP entre o navegador e o ESP8266 (Python 3, sem bibliotecas extras) |
| `vm/simulador_esp.py` | VM ou PC | Faz o papel do ESP8266 para testar sem a placa |
| `vm/relay-esp.service` | VM AWS | Serviço systemd que mantém a ponte rodando |

## 1. Ponte na VM (já instalada)

```bash
cd ~/Aula-16-11/desafio-conectividade-externa/vm
sed "s/TROQUE_ESTE_TOKEN/SEU_TOKEN/" relay-esp.service | sudo tee /etc/systemd/system/relay-esp.service
sudo systemctl daemon-reload
sudo systemctl enable --now relay-esp
```

No grupo de segurança da VM, libere a entrada **TCP 8080** (origem 0.0.0.0/0).

Comandos úteis:

```bash
sudo systemctl status relay-esp          # está rodando?
journalctl -u relay-esp -f               # log ao vivo (Ctrl+C sai)
curl http://localhost:8080/_relay/status  # ESP8266 conectado?
```

## 2. ESP8266

1. Arduino IDE → **Preferências** → URLs adicionais:
   `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
2. **Gerenciador de placas** → instale **esp8266**.
3. Placa: **NodeMCU 1.0 (ESP-12E Module)**; porta COM da placa.
4. No topo do `.ino`, preencha `WIFI_SSID`, `WIFI_SENHA`, `SERVIDOR_HOST` (IP público da VM)
   e `TOKEN` (o mesmo da ponte).
5. Grave e abra o **Monitor Serial** em 115200.
6. Carga: o LED azul da placa já acompanha. Para um relé, ligue IN no **D1**
   (GPIO5), VCC no 5V/VIN e GND no GND. Se o relé ligar invertido,
   use `CARGA_ATIVA_EM_LOW = true`.

> Lâmpada de 127/220 V no relé exige cuidado com a fiação. Para a demonstração,
> um LED ou uma carga de baixa tensão já serve.

## 3. Teste

- **Rede local:** abra `http://<IP local do ESP8266>/` (aparece no Monitor Serial).
  A página mostra "Acesso: direto na rede local".
- **Outra rede:** no celular **com o Wi-Fi desligado (4G)**, abra
  `http://<IP público da VM>:8080/`. A página mostra "Acesso: pela internet (VM AWS)".

Pare o `simulador_esp.py` antes de ligar o ESP8266: os dois não podem rodar juntos.

## Problemas comuns

| Sintoma | Causa provável |
| --- | --- |
| Página "ESP8266 offline" | ESP8266 sem Wi-Fi, IP da VM errado no `.ino` ou token diferente |
| Navegador não abre `:8080` | Porta 8080 não liberada no grupo de segurança, ou VM desligada |
| Serial mostra `servidor respondeu 403` | Token do `.ino` diferente do da ponte |
| Nada funciona depois de religar a VM | A AWS troca o IP público quando a VM é desligada; atualize `SERVIDOR_HOST` |
