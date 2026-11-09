# 📡 Cliente RDT - Entrega 1: Stop-and-Wait (SAW)

Este repositório contém a implementação da **Entrega 1** do projeto final da disciplina de Redes de Computadores (Teleinformática). O objetivo deste código é implementar um cliente UDP confiável utilizando o protocolo **Stop-and-Wait**, lidando com perda de pacotes, retransmissões, validação de integridade e coleta de métricas de rede.

## ⚙️ Funcionalidades Implementadas

- **Handshake Inicial:** Verificação de disponibilidade via `PING/PONG` e negociação de parâmetros via `HELLO/OK`.
- **Transferência Confiável (Stop-and-Wait):** 
  - Fluxo rigoroso de requisição (`REQ`), recebimento (`DATA`) e confirmação (`ACK`).
  - Tratamento de temporizadores (*Timeout*) e retransmissões automáticas em caso de perda de pacotes.
- **Encerramento Seguro:** Envio da assinatura digital do arquivo (`FIN`) e aguardo da confirmação de integridade do servidor (`DONE`).
- **Exportação de Métricas:** Geração automática de um arquivo CSV contendo os dados de tempo e vazão de cada segmento.
- **Visualização de Dados:** Geração de um gráfico de linha duplo (RTT e Throughput) usando a biblioteca `matplotlib`.

## 🛠️ Pré-requisitos

O projeto foi desenvolvido em **Python 3**. A única dependência externa necessária é a biblioteca `matplotlib` para a geração do gráfico de métricas.

Para instalar a dependência, execute o comando abaixo no seu terminal:

```bash
pip install matplotlib
```

## 🚀 Como Executar

O cliente exige a passagem de argumentos obrigatórios via linha de comando (`--server`, `--group`, `--file`).

Execute o programa com o seguinte formato:

```bash
python3 cliente.py --server 137.131.178.229 --group Grupo06 --file small
```

**Parâmetros:**
* `--server`: Endereço IP do servidor da disciplina.
* `--group`: Identificador do seu grupo (ex: `Grupo06`).
* `--file`: Tamanho do arquivo desejado (`small`, `medium` ou `large`).

## 📁 Arquivos Gerados

Tudo é salvo dentro da pasta do projeto, de onde quer que o cliente seja executado:

```
├── cliente.py                 # Cliente RDT-UnB (SAW, GBN e SR, timeout fixo ou adaptativo)
├── comparar.py                # Tabelas comparativas e gráficos (Entregas 2, 3 e relatório final)
├── experimentos.py            # Roda em sequência os lotes de testes da Entrega 3
├── docs/                      # Relatórios entregues
├── recebidos/                 # Arquivos baixados e validados (ignorado no git)
│   └── received_<arquivo>
└── resultados/
    ├── resumo.csv             # Uma linha por execução (base da tabela comparativa)
    └── <arquivo>/             # small | medium | large
        ├── <cenario>/         # ex: saw_w01_p00, gbn_w16_p10, sr_w16_p10_adapt_a0.125_b0.25_min60
        │   ├── metrics_<grupo>_<protocolo>_<timestamp>.csv
        │   └── grafico_<grupo>_<protocolo>_<timestamp>.png
        └── comparacao/        # Gerado pelo comparar.py
            ├── tabela.md, gbn_vs_sr_w16_p10.png, throughput_por_janela.png   # Entrega 2
            ├── tabela_alfa_beta.md, alfa_beta_replay.png                       # Entrega 3: α, β e piso
            ├── tabela_timeout.md, timeout_fixo_vs_adaptativo.png               # Entrega 3: fixo x adaptativo
            └── tabela_final.md, throughput_final.png                           # Relatório final
```

O nome do cenário é `<protocolo>_w<janela>_p<perda %>`, com dois dígitos para a ordenação ficar correta. Com timeout adaptativo, o nome ganha o sufixo `_adapt_a<α>_b<β>_min<piso em ms>`. O CSV mantém o padrão exigido pela especificação (`metrics_<grupo>_<protocolo>_<timestamp>.csv`). O gráfico usa o mesmo sufixo, então cada gráfico fica ao lado do CSV que o gerou. Execuções repetidas do mesmo cenário se acumulam na mesma pasta, diferenciadas pelo timestamp.

Para o SAW sem perda (Entrega 1), os arquivos ficam em `resultados/<arquivo>/saw_w01_p00/`. O gráfico mostra, ao longo dos segmentos, o RTT medido e o RTT estimado (EWMA), o timeout em vigor, o throughput e as retransmissões.

## 📊 Comportamento de Rede Esperado (Análise de RTT)

Ao analisar o gráfico gerado, é normal observar um RTT muito baixo (alta velocidade) nos primeiros segmentos da transferência, seguido de um aumento abrupto e estabilização de um RTT mais alto na maior parte do arquivo. 

Isso **não é um erro** no código. Trata-se do esgotamento da capacidade de rajada (*burst*) do algoritmo de controle de banda (como o *Token Bucket*) implementado no servidor. O servidor processa os primeiros pacotes imediatamente com os *tokens* acumulados e, em seguida, enfileira os pacotes subsequentes para respeitar a limitação de banda imposta artificialmente para a disciplina, resultando na queda do *throughput* geral.
---

# 📡 Entrega 2: Janela Deslizante (Go-Back-N e Selective Repeat)

O mesmo `cliente.py` implementa os três protocolos. Sem os novos argumentos ele continua rodando o Stop-and-Wait da Entrega 1.

```bash
python3 cliente.py --server 137.131.178.229 --group Grupo06 --file small --protocol gbn --window 8 --loss 0.05
```

**Novos parâmetros:**
* `--protocol`: `saw` (padrão), `gbn` ou `sr`.
* `--window`: tamanho da janela N para `gbn`/`sr` (padrão 4; testar 4, 8 e 16). O SAW sempre usa janela 1.
* `--loss`: probabilidade de perda simulada, de 0 a 1 (ex: `0.05` = 5%). Padrão 0, que é o modo da demo ao vivo.
* `--timeout`: timeout fixo em segundos (padrão 1.0).
* `--seed`: semente do sorteio de perda, para repetir o mesmo padrão de perdas entre execuções.

## Comportamento dos protocolos

- **GBN:** mantém até N REQs pendentes e usa um único timer (o do segmento `base`). Só aceita o DATA de `seq == base`. Qualquer DATA fora de ordem é descartado. No timeout, reenvia o REQ do `base` e de todos os seguintes já enviados.
- **SR:** mantém até N REQs pendentes, com um timer por segmento. Aceita DATA fora de ordem dentro da janela e guarda no buffer. Entrega ao arquivo em ordem quando o `base` chega. No timeout, reenvia apenas o REQ daquele segmento.

## Simulação de perda

Abordagem escolhida: **(a) descartar o DATA recebido com probabilidade P antes de processá-lo.** O servidor é *pull-based*: ele só envia o que o cliente pede. Por isso, deixar de enviar um ACK (abordagem b) não provocaria nenhuma retransmissão, já que o cliente já teria o dado. Descartar o DATA faz o cliente agir como se o pacote tivesse se perdido na rede e esperar o timeout para reenviar o REQ.

## CSV e métricas

A estrutura de pastas está descrita em [Arquivos Gerados](#-arquivos-gerados).

- `metrics_<grupo>_<protocolo>_<timestamp>.csv`: colunas obrigatórias + `simulated_loss` (1 se algum DATA deste segmento foi descartado pela simulação). No GBN, `timeout_occurred = 1` apenas no segmento cujo timer expirou. Já `retransmissions` conta também os reenvios "de carona" dos segmentos seguintes. Assim, retransmissões ÷ timeouts = segmentos reenviados por erro.
- `throughput_kbps` (GBN/SR): bits dos últimos N segmentos aceitos ÷ tempo em que chegaram. Com N = 1 isso equivale à definição do SAW.
- `resultados/resumo.csv`: uma linha por execução (tempo total, throughput efetivo = tamanho do arquivo ÷ tempo total, retransmissões, timeouts, MD5 OK...).

## Tabela comparativa e gráficos

Depois de rodar os 21 cenários (SAW, GBN 4/8/16, SR 4/8/16 × 0%, 5%, 10%):

```bash
python3 comparar.py --file small --window 16 --loss 0.10
```

O script lê `resultados/resumo.csv`, usando a execução mais recente de cada cenário com MD5 OK. Ele grava em `resultados/<arquivo>/comparacao/`:

- `tabela.md`: throughput / retransmissões / tempo total por protocolo × janela × perda, mais retransmissões por timeout.
- `gbn_vs_sr_w16_p10.png`: throughput e retransmissões acumuladas por segmento.
- `throughput_por_janela.png`: throughput sem perda em função da janela.

---

# 📡 Entrega 3: RTT Adaptativo

O timeout adaptativo funciona com os três protocolos e é ativado com `--adaptive`. Sem a flag, o cliente usa o timeout fixo de `--timeout`, como nas entregas anteriores.

```bash
python3 cliente.py --server 137.131.178.229 --group Grupo06 --file small --protocol sr --window 16 --loss 0.1 --adaptive
```

**Novos parâmetros:**
* `--adaptive`: liga o timeout adaptativo. Nesse modo, `--timeout` vira o timeout inicial, usado até chegar a primeira amostra de RTT.
* `--alpha`: peso α da EWMA do RTT (padrão 0.125, o valor do TCP).
* `--beta`: peso β da EWMA do DevRTT (padrão 0.25, o valor do TCP).
* `--timeout-min`: piso do timeout adaptativo em segundos (padrão 0.06).

## Como o timeout é calculado (classe `Temporizador`)

A cada amostra válida de RTT, medida do último REQ enviado até o DATA do segmento:

```
RTT_est = (1 - α) × RTT_est + α × RTT_medido
DevRTT  = (1 - β) × DevRTT  + β × |RTT_medido - RTT_est|
timeout = max(RTT_est + 4 × DevRTT, timeout_min)
```

- **Primeira amostra (RFC 6298):** RTT_est = R e DevRTT = R/2.
- **Algoritmo de Karn:** se um segmento teve mais REQs enviados do que DATAs recebidos, não dá para saber a qual REQ o DATA responde, e a amostra é ignorada. O cliente conta REQs e DATAs por segmento (`amostra_valida`). Assim, no GBN, os segmentos reenviados "de carona" continuam gerando amostras, porque o DATA original deles já tinha chegado (e sido descartado por estar fora de ordem). Contar só "segmento sem retransmissão" deixava o GBN sem amostras sob perda, e o timeout subia até o teto. Um DATA descartado pela perda simulada não conta como recebido.
- **Backoff exponencial:** cada timeout dobra o valor atual (teto de 3 s) até chegar uma nova amostra válida. Se o RTT subir de repente (ex.: atraso extra no cenário surpresa), o timeout acompanha em vez de ficar retransmitindo para sempre. No SR, vários timers vencendo na mesma rodada contam como um único evento.
- **Timeout mínimo:** em períodos estáveis o DevRTT cai para ~1 ms e o timeout fica colado no RTT (~22 ms). Quando o servidor enfileira (token bucket), o RTT pula para 30–60 ms, a janela inteira expira à toa e as retransmissões aumentam ainda mais a fila. É o mesmo motivo do RTO mínimo do TCP real (1 s na RFC 6298, 200 ms no Linux). O valor de 60 ms veio dos dados: é o menor piso que elimina essa cascata (ver `tabela_alfa_beta.md`).
- **Ordem de leitura:** antes de declarar timeout, o GBN e o SR leem o que já está no buffer do socket, para que um DATA que já chegou não vire timeout.

A EWMA é calculada também no modo fixo, então a coluna `rtt_estimated_ms` vem preenchida em todas as execuções. A coluna `timeout_ms` registra o timeout em vigor no último REQ enviado para o segmento.

**Mudança no CSV em relação à Entrega 1:** `rtt_ms` do SAW agora mede do **último** REQ enviado até o DATA, igual ao GBN e ao SR e ao que o Wireshark mostra. Antes media desde o primeiro REQ e incluía os timeouts. O `throughput_kbps` do SAW continua considerando todo o tempo gasto no segmento.

O `resumo.csv` ganhou as colunas `timeout_modo`, `alpha`, `beta`, `timeout_min_ms`, `timeout_medio_ms`, `erro_estimador_ms` (erro médio de previsão do RTT_est) e `duplicados` (DATAs recebidos de segmentos já aceitos, ou seja, retransmissões que não eram necessárias). Um `resumo.csv` antigo é convertido automaticamente: as linhas da Entrega 2 ficam marcadas como timeout fixo.

## Experimentos e análises

O `experimentos.py` roda cada lote de execuções em sequência, sempre com a mesma semente de perda (`--seed 1`), e no fim gera a análise correspondente. Use `--dry-run` para só listar os comandos.

| Plano | Execuções | Análise gerada |
|---|---|---|
| `alfa-beta` | SR 16, 10% de perda, adaptativo com (α, β) = (0.125, 0.25), (0.05, 0.25), (0.25, 0.25), (0.5, 0.25), (0.125, 0.125), (0.125, 0.5) | `tabela_alfa_beta.md`, `alfa_beta_replay.png` |
| `piso` | SR 16, 0% e 10% de perda, timeout mínimo de 0, 30, 60 e 100 ms | `tabela_alfa_beta.md` |
| `timeout` | GBN 16 e SR 16, 5% e 10% de perda, timeout fixo e adaptativo | `tabela_timeout.md`, `timeout_fixo_vs_adaptativo.png` |
| `final` | SAW, GBN 16 e SR 16 (fixo e adaptativo), sem perda | `tabela_final.md`, `throughput_final.png` |

```bash
python3 experimentos.py --plano alfa-beta --server 137.131.178.229 --group Grupo06 --file small
```

```bash
python3 experimentos.py --plano piso --server 137.131.178.229 --group Grupo06 --file small
```

```bash
python3 experimentos.py --plano timeout --server 137.131.178.229 --group Grupo06 --file small --alpha 0.125 --beta 0.25
```

```bash
python3 experimentos.py --plano final --server 137.131.178.229 --group Grupo06 --file large --alpha 0.125 --beta 0.25
```

No plano `timeout`, `--sem-fixo` reaproveita as execuções com timeout fixo que já estão no `resumo.csv` (as da Entrega 2). Nos planos `timeout` e `final`, passe em `--alpha`, `--beta` e `--timeout-min` os valores escolhidos na análise de α e β.

As análises também podem ser geradas direto, com `python3 comparar.py --analise <janelas|alfa-beta|timeout|final> --file <arquivo>`:

- **`alfa-beta`:** junta três partes. As execuções reais por par (α, β). As execuções reais por timeout mínimo. E um **replay offline**: a EWMA é reaplicada, com toda a grade de α ∈ {0.05, 0.125, 0.25, 0.5} × β ∈ {0.125, 0.25, 0.5} e com vários pisos, sobre a **mesma** série de RTTs medidos (por padrão, a última execução sem perda; troque com `--csv`). A comparação fica justa porque todos os pares veem exatamente a mesma rede. Para cada par, mostra o erro médio de previsão (efeito de α), a porcentagem de RTTs que teriam estourado o timeout (retransmissões espúrias, efeito de β e do piso) e o timeout médio (tempo para detectar uma perda real). O gráfico `alfa_beta_replay.png` mostra o RTT estimado para cada α e o timeout para cada β ao longo dos segmentos (`--faixa 0:500`).
- **`timeout`:** a tabela fixo × adaptativo pedida no relatório (retransmissões, tempo total, throughput) e o gráfico de barras do tempo total.
- **`final`:** a tabela integrada do relatório final (SAW, GBN 16 e SR 16 com timeout fixo e adaptativo) e o gráfico de barras do throughput médio. Por padrão usa as execuções sem perda; mude com `--loss`.

## Wireshark (relatório final)

1. Abra o Wireshark na interface de rede usada e aplique o filtro de captura ou de exibição `udp and host 137.131.178.229`.
2. Rode uma transferência com o arquivo `large`, por exemplo `python3 cliente.py --server 137.131.178.229 --group Grupo06 --file large --protocol sr --window 16 --adaptive`.
3. Filtros de exibição úteis (o payload do protocolo é texto puro):
   - Sessão completa: `udp and host 137.131.178.229`.
   - Um segmento específico, com REQ original, REQ retransmitido, DATA e ACK: `data matches "seq=1234($|\\|)"`. Os REQ e ACK terminam em `seq=N`, e o DATA tem `seq=N|` no meio; o `($|\\|)` evita pegar também o 12345.
   - Só os REQs: `data matches "^REQ"`.
4. Para achar retransmissões, filtre no CSV as linhas com `retransmissions > 0`, pegue o `segment` e procure os REQs desse `seq` no Wireshark. Com *View → Time Display Format → Time of Day*, o horário das capturas fica no mesmo relógio do `timestamp` do CSV, que é o horário de chegada do DATA aceito.
5. RTT no Wireshark: diferença entre o último REQ de um `seq` e o DATA correspondente. Deve bater com `rtt_ms` do CSV, a menos de ~1 ms de processamento do cliente.
