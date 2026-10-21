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
├── cliente.py                 # Cliente RDT-UnB (SAW, GBN e SR)
├── comparar.py                # Tabela comparativa e gráficos da Entrega 2
├── docs/                      # Relatórios entregues
├── recebidos/                 # Arquivos baixados e validados (ignorado no git)
│   └── received_<arquivo>
└── resultados/
    ├── resumo.csv             # Uma linha por execução (base da tabela comparativa)
    └── <arquivo>/             # small | medium | large
        ├── <cenario>/         # ex: saw_w01_p00, gbn_w16_p10, sr_w04_p05
        │   ├── metrics_<grupo>_<protocolo>_<timestamp>.csv
        │   └── grafico_<grupo>_<protocolo>_<timestamp>.png
        └── comparacao/        # Gerado pelo comparar.py
            ├── tabela.md
            ├── gbn_vs_sr_w16_p10.png
            └── throughput_por_janela.png
```

O nome do cenário é `<protocolo>_w<janela>_p<perda %>`, com dois dígitos para a ordenação ficar correta. O CSV mantém o padrão exigido pela especificação (`metrics_<grupo>_<protocolo>_<timestamp>.csv`). O gráfico usa o mesmo sufixo, então cada gráfico fica ao lado do CSV que o gerou. Execuções repetidas do mesmo cenário se acumulam na mesma pasta, diferenciadas pelo timestamp.

Para o SAW sem perda (Entrega 1), os arquivos ficam em `resultados/<arquivo>/saw_w01_p00/`. O gráfico mostra RTT, throughput e retransmissões ao longo dos segmentos.

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
