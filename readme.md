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

Após a execução bem-sucedida, o programa gerará automaticamente três arquivos no diretório atual:

1. `received_<tamanho_do_arquivo>`: O arquivo binário baixado e validado (ex: `received_small`).
2. `metricas_saw.csv`: Planilha contendo as colunas de Sequência, RTT, Throughput, Retransmissões e ocorrências de Timeout para análise detalhada.
3. `grafico_saw.png`: Imagem contendo o gráfico que relaciona o tempo de ida e volta (RTT) e a taxa de transferência (Throughput) ao longo dos segmentos baixados.

## 📊 Comportamento de Rede Esperado (Análise de RTT)

Ao analisar o gráfico gerado, é normal observar um RTT muito baixo (alta velocidade) nos primeiros segmentos da transferência, seguido de um aumento abrupto e estabilização de um RTT mais alto na maior parte do arquivo. 

Isso **não é um erro** no código. Trata-se do esgotamento da capacidade de rajada (*burst*) do algoritmo de controle de banda (como o *Token Bucket*) implementado no servidor. O servidor processa os primeiros pacotes imediatamente com os *tokens* acumulados e, em seguida, enfileira os pacotes subsequentes para respeitar a limitação de banda imposta artificialmente para a disciplina, resultando na queda do *throughput* geral.